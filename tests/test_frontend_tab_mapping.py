"""Раунд 10.6 (T-1211) — тест-аудит маппинга групп → вкладок новой IA:
11 модулей (mod_*) + 7 подразделов AI; каждая конфиг-группа ровно на одной
вкладке; зеркало TABS (web/app.js) синхронно с TAB_RULES.
"""
import pytest

from services import param_catalog as pc
from services.param_catalog import (
    CATEGORIES,
    GROUPS,
    TAB_CHAT_LORE,
    TAB_LLM_PROVIDERS,
    TAB_MEMORY_RAG,
    TAB_MOD_CHECKUP,
    TAB_MOD_DIRECT,
    TAB_MOD_FACTCHECK,
    TAB_MOD_MEDIA_DOWNLOAD,
    TAB_MOD_NOSTALGIA,
    TAB_MOD_SEARCH,
    TAB_MOD_SLEEP,
    TAB_MOD_SUMMARY,
    TAB_MOD_TRANSCRIBE,
    TAB_MOD_VIDEO_SUMMARY,
    TAB_MOD_WEB,
    TAB_PEOPLE_NAMES,
    TAB_PERMSOC,
    TAB_PROMPTS,
    TAB_RELATIONS,
    TAB_SMART_CACHE,
    group_tab,
    tab_group_ids,
)

CONFIG_CATEGORIES = ("models", "keys", "prompts", "limits", "flags", "reactions")

ALL_TABS = [
    TAB_MOD_SUMMARY, TAB_MOD_DIRECT, TAB_MOD_FACTCHECK, TAB_MOD_SEARCH,
    TAB_MOD_TRANSCRIBE, TAB_MOD_VIDEO_SUMMARY, TAB_MOD_MEDIA_DOWNLOAD,
    TAB_MOD_WEB, TAB_MOD_CHECKUP, TAB_MOD_SLEEP, TAB_MOD_NOSTALGIA,
    TAB_LLM_PROVIDERS, TAB_PROMPTS, TAB_MEMORY_RAG, TAB_SMART_CACHE,
    TAB_PEOPLE_NAMES, TAB_RELATIONS, TAB_CHAT_LORE, TAB_PERMSOC,
]


class TestTabMappingAudit:
    def test_19_config_tabs(self):
        assert len(ALL_TABS) == 19
        assert len(pc.TAB_RULES) == 19
        assert set(pc.CONFIG_TAB_TITLES) == set(ALL_TABS)

    def test_every_config_group_assigned_to_exactly_one_tab(self):
        seen = {}
        for g in GROUPS:
            if g.category not in CONFIG_CATEGORIES:
                continue
            tab = group_tab(g.id)
            assert tab is not None, f"группа {g.id} не приписана вкладке"
            assert tab in ALL_TABS
            seen.setdefault(tab, []).append(g.id)
        for tab, groups in seen.items():
            assert len(groups) == len(set(groups))

    def test_every_group_belongs_to_one_tab(self):
        by_tab = [set(tab_group_ids(t)) for t in ALL_TABS]
        union = set().union(*by_tab)
        for g in GROUPS:
            if g.category in CONFIG_CATEGORIES:
                assert g.id in union
        for a in range(len(by_tab)):
            for b in range(a + 1, len(by_tab)):
                assert by_tab[a].isdisjoint(by_tab[b])

    def test_mapped_and_counts(self):
        # 90 GROUPS − 2 content (tab=None) = 88 mapped; 10.9: +7 display,
        # −reactions_persons → REGISTRY 400.
        assert len(pc._TAB_BY_GROUP) == 88
        assert len(GROUPS) == 90
        assert len(pc.REGISTRY) == 405


class TestModuleTabs:
    def test_mod_summary_composition(self):
        assert tab_group_ids(TAB_MOD_SUMMARY) == {
            "flags_module_summary", "flags_summary", "limits_summary",
            "reactions_summary"}

    def test_mod_direct_composition(self):
        assert tab_group_ids(TAB_MOD_DIRECT) == {
            "flags_module_direct", "flags_chat_behavior", "limits_chat",
            "limits_chat_behavior", "limits_chat_budgets", "limits_temperature",
            "reactions_chat"}

    def test_mod_factcheck_and_search(self):
        assert tab_group_ids(TAB_MOD_FACTCHECK) == {
            "flags_module_factcheck", "limits_factcheck"}
        assert tab_group_ids(TAB_MOD_SEARCH) == {
            "flags_module_search", "limits_search"}

    def test_mod_transcribe_composition(self):
        assert tab_group_ids(TAB_MOD_TRANSCRIBE) == {
            "flags_module_transcribe", "limits_transcribe"}

    def test_mod_video_summary_has_keys_youtube(self):
        # A8/T-1204: keys_youtube (proxy+cookies) — в Модуле 6, не в LLM.
        groups = tab_group_ids(TAB_MOD_VIDEO_SUMMARY)
        assert "keys_youtube" in groups
        assert "limits_youtube" in groups
        assert "limits_youtube_proxy" in groups
        assert "keys_youtube" not in tab_group_ids(TAB_LLM_PROVIDERS)

    def test_mod_media_download(self):
        assert tab_group_ids(TAB_MOD_MEDIA_DOWNLOAD) == {
            "flags_module_media_download", "limits_media_download"}

    def test_mod_web(self):
        assert tab_group_ids(TAB_MOD_WEB) == {"flags_module_web", "limits_web"}

    def test_mod_checkup_has_diagnostics_settings(self):
        # A8/T-1205: models_checkup + keys_betterstack — в «Диагностике».
        groups = tab_group_ids(TAB_MOD_CHECKUP)
        assert groups == {
            "flags_service", "flags_throttle", "limits_checkup",
            "limits_service", "limits_worker", "models_checkup",
            "keys_betterstack"}
        assert "models_checkup" not in tab_group_ids(TAB_LLM_PROVIDERS)
        assert "keys_betterstack" not in tab_group_ids(TAB_LLM_PROVIDERS)

    def test_mod_sleep_and_nostalgia(self):
        assert tab_group_ids(TAB_MOD_SLEEP) == {"memory_dream"}
        assert tab_group_ids(TAB_MOD_NOSTALGIA) == {"memory_nostalgia"}


class TestAiTabs:
    def test_llm_providers_covers_models_and_keys(self):
        models = {g.id for g in GROUPS if g.category == "models"}
        keys = {g.id for g in GROUPS if g.category == "keys"}
        # A8: checkup-настройки ушли в М9, keys_youtube — в М6.
        assert tab_group_ids(TAB_LLM_PROVIDERS) == (
            models | keys) - {"models_checkup", "keys_betterstack",
                              "keys_youtube"}

    def test_memory_rag_has_limits_rag(self):
        # A3/T-1208: RAG-доли/дедуп → «Память».
        groups = tab_group_ids(TAB_MEMORY_RAG)
        assert "limits_rag" in groups
        assert "limits_memory" in groups and "limits_graph" in groups
        assert "reactions_memory" in groups

    def test_smart_cache(self):
        assert tab_group_ids(TAB_SMART_CACHE) == {
            "limits_smart_cache", "flags_smart_cache"}

    def test_relocated_params_are_in_new_groups(self):
        by_pg = {s.pg_key: s for s in pc.REGISTRY.values()}
        # RAG-ключи в limits_rag (не в Модуле 2)
        assert by_pg["limits.chat_budget_rag_ratio"].group == "limits_rag"
        assert by_pg["limits.chat_rag_dedup_overlap_ratio"].group == "limits_rag"
        # 10 миселённых ключей — в М5/М6/М7
        assert by_pg["limits.download_cooldown"].group == "limits_media_download"
        assert by_pg["limits.voice_max_duration_seconds"].group == "limits_transcribe"
        assert by_pg["limits.video_summary_min_chars"].group == "limits_video_summary"
        assert by_pg["limits.stt_groq_max_upload_mb"].group == "limits_transcribe"
        # Леха/Костик раздельно
        assert by_pg["limits.alan_reply_interval"].group == "limits_alan"
        assert by_pg["limits.kostik_reply_probability"].group == "limits_kostik"
        assert by_pg["reactions.kostik_user_id"].group == "reactions_kostik"
        assert by_pg["reactions.alan_user_id"].group == "reactions_alan"


class TestJsMirror:
    JS = open("web/app.js", encoding="utf-8").read()
    HTML = open("web/index.html", encoding="utf-8").read()

    def test_11_modules_in_js(self):
        for mid in ALL_TABS[:11]:
            assert "id: '%s'" % mid in self.JS, mid
        assert self.JS.count("mod_") >= 11

    def test_no_sidebar(self):
        for token in ("sidebarOpen", "MENU_ORDER", "MENU_LABELS"):
            assert token not in self.JS, token
        assert "sidebar" not in self.HTML
        assert "☰" not in self.HTML

    def test_nav_labels(self):
        assert 'class="nav-label"' in self.HTML
        assert ".nav-label" in self.HTML
        assert ".nav-link > span:not(.msr) { display: none; }" not in self.HTML

    def test_scroll_area(self):
        assert "scroll-area" in self.HTML
        assert ".fullscreen-mode .scroll-area" in self.HTML

    def test_smart_cache_and_7_ai_cards(self):
        assert "id: 'smart_cache'" in self.JS
        assert "'#/ai/smart-cache'" in self.JS

    def test_provider_blocks_and_test_endpoint(self):
        assert "PROVIDER_BLOCKS" in self.JS
        assert "/api/llm/test" in self.JS
        assert "direct_main" in self.JS and "direct_fallback" in self.JS
        assert "video_summary_openrouter" in self.JS

    def test_access_windows(self):
        # 10.8 (§4, ADR-001): три подраздела — route-driven модальные окна.
        assert "accessOpen" in self.JS
        assert "openAccessWindow: function (id)" in self.JS
        assert "closeAccessWindow: function ()" in self.JS
        assert "setAccess" not in self.JS
        assert 'class="modal-backdrop"' in self.HTML
        assert 'class="acc-head"' not in self.HTML
        assert 'role="tabpanel"' not in self.HTML

    def test_no_emoji_in_how_and_matrix(self):
        assert "ℹ️ Как это работает" not in self.HTML
        assert "🔐 Матрица ролей" not in self.HTML

    def test_no_old_section_labels_in_web(self):
        # 10.8 (§1/§9 grep-гейт): старые подписи разделов отсутствуют.
        for old in ("label: 'Как это работает'", "label: 'Настройки AI'",
                    "label: 'Функции PERMsoc'", "label: 'Доступы и Роли'",
                    "label: 'Oversight'",
                    "«Как это работает»", "«Функции PERMsoc»"):
            assert old not in self.JS, old
            assert old not in self.HTML, old

    def test_removed_tabs_not_in_js(self):
        for old in ("limits", "memory_dream", "memory_nostalgia",
                    "reactions_triggers", "modules_switches", "modules_feats"):
            assert ("id: '%s'" % old) not in self.JS, old
        assert "Кастомные модули" not in self.JS


def test_widget_keyvalue_on_summary_aliases():
    spec = next(s for s in pc.REGISTRY.values()
                if s.pg_key == "limits.summary_aliases")
    assert spec.widget == "keyvalue"
    sel = [s for s in pc.REGISTRY.values() if s.widget == "select"]
    assert len(sel) == 1
    assert sel[0].pg_key == "limits.chat_temperature_preset_default"
