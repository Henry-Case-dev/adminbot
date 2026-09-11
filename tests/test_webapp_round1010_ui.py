"""Раунд 10.10 (admin-ui-round1010) — UI-маркеры + инварианты.

Покрывается:
  * п.1 — fullscreen-паддинг шапки: max(env, --tg-content-safe-area-*,
    --tg-safe-area-inset-*); 10.7/10.9 не сломаны;
  * п.2 — mobile key-availability chart: keyHistoryChartModel (дорожки,
    временная сетка, динамическая высота), контракт не тронут;
  * п.3 — «Провайдеры»: реальные значения (контролируемый :value);
  * п.4 — DM-дефолты (gates/overrides OFF) + скрипт (без бота не тут);
  * п.5 — «Роли»: аватар+ник, мелкий серый ID, ширины.

Все проверки — статические grep-маркеры (как test_webapp_round109_ui).
"""
from pathlib import Path

ROOT = Path(".")
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CHAT_PARAMS = (ROOT / "services" / "chat_params.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "web" / "api" / "routes.py").read_text(encoding="utf-8")
AVATARS = (ROOT / "web" / "api" / "avatars.py").read_text(encoding="utf-8")


def _admins_section() -> str:
    """Секция окна «Роли» (#/access/admins) — без соседних окон."""
    start = HTML.index("isAccessOpen('admins')")
    end = HTML.index("isAccessOpen('roles')")
    return HTML[start:end]


class TestHeaderFullscreen:
    def test_fullscreen_rule_present(self):
        assert ".fullscreen-mode header.header-sticky" in HTML
        assert "--tg-content-safe-area-inset-top" in HTML
        assert "max(env(safe-area-inset-top" in HTML
        assert "var(--tg-safe-area-inset-top" in HTML

    def test_107_and_109_intact(self):
        # 10.7: базовый safe-area по ширине сохранён.
        assert "padding-right: calc(1rem + env(safe-area-inset-right" in HTML
        assert "padding-left: calc(1rem + env(safe-area-inset-left" in HTML
        # 10.9: модель скролла fullscreen сохранена.
        assert ".fullscreen-mode .scroll-area" in HTML
        assert "overflow-y: auto" in HTML


class TestKeyHistoryChart:
    def test_model_extracted(self):
        assert "keyHistoryChartModel: function" in JS
        # дорожки не сливаются: смещение на lane.
        assert "lane + 0.75" in JS
        assert "lane + 0.25" in JS
        assert "Math.max(120, 44 +" in JS

    def test_window_built_from_end_high1(self):
        # HIGH-1: окно от конца (minStart), без break/slice старого окна.
        assert "minStart" in JS
        assert "MAX_HISTORY_POINTS - 1" in JS
        assert "MAX_HISTORY_POINTS * 2" not in JS
        assert "grid.slice(-MAX_HISTORY_POINTS)" not in JS

    def test_responsive_height(self):
        assert "maintainAspectRatio: false" in JS
        assert "keyHistoryChartHeight" in JS
        assert "keyHistoryChartHeight + 'px'" in HTML
        assert 'class="keys-chart' in HTML

    def test_existing_markers_preserved(self):
        assert "stepped: true" in JS
        assert "legend: { display: true" in JS
        assert 'ref="keyHistoryCanvas"' in HTML

    def test_endpoint_contract_untouched(self):
        body = ROUTES[ROUTES.index("async def get_status_key_history"):]
        body = body[:body.index("async def get_status_logs")]
        assert "return key_history.api_payload()" in body


class TestProviderFieldHydration:
    def test_controlled_value_not_vmodel(self):
        assert 'v-model="blockDrafts[f.key]"' not in HTML
        assert ':value="blockFieldValue(f)"' in HTML
        assert "@input=\"blockDrafts[f.key] = $event.target.value\"" in HTML

    def test_block_field_value_empty_draft_not_rollback(self):
        assert "if (draft != null) return draft;" in JS
        assert "if (draft != null && draft !== '') return draft;" not in JS

    def test_drafts_reset_on_load_and_scope(self):
        idx = JS.index("loadConfig: async function")
        chunk = JS[idx:idx + 1600]
        assert "this.blockDrafts = {};" in chunk
        sc = JS.index("setActiveChat: function")
        sc_chunk = JS[sc:sc + 2200]
        assert "this.blockDrafts = {};" in sc_chunk
        assert "this.blockResults = {};" in sc_chunk


class TestDmDefaultsBackend:
    def test_disabled_constants(self):
        assert "_DM_DISABLED_GATES" in CHAT_PARAMS
        assert "_DM_DISABLED_OVERRIDES" in CHAT_PARAMS
        for key in ("memory.dream_enabled", "memory.nostalgia_enabled",
                    "flags.summary_enabled",
                    "flags.chat_running_summary_enabled"):
            assert key in CHAT_PARAMS, key
        assert '"dream": False' in CHAT_PARAMS
        assert '"nostalgia": False' in CHAT_PARAMS

    def test_ensure_scope_profile_uses_defaults(self):
        body = CHAT_PARAMS[CHAT_PARAMS.index("async def ensure_scope_profile"):]
        body = body[:body.index("async def get_chat_param_defaulted")]
        assert "dict(_DM_DISABLED_GATES)" in body
        assert "dict(_DM_DISABLED_OVERRIDES)" in body
        # групповой путь не тронут (INSERT_DEFAULT_PROFILE).
        assert "INSERT_DEFAULT_PROFILE" in body

    def test_bot_router_gate_not_touched(self):
        bot = (ROOT / "bot.py").read_text(encoding="utf-8")
        assert "flags.summary_enabled" in bot
        assert "chat_summary_enabled" not in bot

    def test_script_declared(self):
        script = (ROOT / "scripts" / "disable_dm_heavy_modules.py").read_text(
            encoding="utf-8")
        for marker in ("build_dm_patch", "collect_plan", "write_snapshot",
                       "fetch_dm_profiles", "apply_plan",
                       "restore_from_snapshot", "--apply", "--dry-run",
                       "--chat-id", "--snapshot-out", "--restore"):
            assert marker in script, marker


class TestRolesUi:
    def test_avatar_name_and_small_id(self):
        section = _admins_section()
        assert "admin.avatarUrl" in section
        assert "@error=\"avatarError(admin)\"" in section
        assert "adminInitial(admin)" in section
        # Scanner LOW: недостижимая ветка admin.username удалена.
        assert "admin.display_name" in section
        assert "admin.username" not in section
        assert "text-[10px] text-gray-500 font-mono" in section
        assert "{{ admin.telegram_id }}</b>" not in section

    def test_widths_and_button(self):
        section = _admins_section()
        assert 'class="field w-24"' in section
        assert 'class="field flex-1 min-w-0" type="number"' in section
        assert 'class="btn-accent text-sm shrink-0"' in section

    def test_admin_initial_helper_reuses_avatar_initial(self):
        assert "adminInitial: function" in JS
        # Scanner LOW: без дубля графем-логики — делегирует avatarInitial.
        assert "this.avatarInitial(" in JS
        block = JS[JS.index("adminInitial: function"):]
        block = block[:block.index("loadRoles: async function")]
        assert "Array.from" not in block
        # negatives не перезагружаются повторно.
        assert "avatarSkipped" in JS
        assert "if (!url) a.avatarSkipped = true;" in JS

    def test_close_buttons_count_unchanged(self):
        # 10.8/10.9-инвариант: ровно 4 модальных ✕ (новых не добавляли).
        assert HTML.count(">✕</button>") == 4

    def test_backend_enrichment_markers(self):
        assert "global_user_display_info" in AVATARS
        assert "bot.get_chat(user_id)" in AVATARS
        assert "get_user_profile_photos(user_id, limit=1)" in AVATARS
        assert "_user_name_cache" in AVATARS
        assert "global_user_display_info" in ROUTES
        assert "display_name" in ROUTES


class TestCatalog1010:
    def test_counts(self):
        import dataclasses
        from config.settings import Settings
        from services import param_catalog as pc
        assert len(pc.REGISTRY) == 400
        assert len(pc.GROUPS) == 90
        assert len(pc._TAB_BY_GROUP) == 88
        assert len(pc.TAB_RULES) == 19
        assert len({f.name for f in dataclasses.fields(Settings)}) == 372
