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
    TAB_MOD_BUDGETS,
    TAB_MOD_DIRECT,
    TAB_MOD_FACTCHECK,
    TAB_MOD_IMAGES,
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
    TAB_MOD_BUDGETS, TAB_MOD_IMAGES,
    TAB_LLM_PROVIDERS, TAB_PROMPTS, TAB_MEMORY_RAG, TAB_SMART_CACHE,
    TAB_PEOPLE_NAMES, TAB_RELATIONS, TAB_CHAT_LORE, TAB_PERMSOC,
]


class TestTabMappingAudit:
    def test_21_config_tabs(self):
        # 10.19 (F3/ADR-1019-3 D1): +1 — mod_budgets («Бюджеты», nav «Модули»).
        # 10.24 (F5/ADR-1024-9 D1): +1 — mod_images («Генерация изображений»,
        # nav «Модули»; группа flags_module_images перенесена из mod_direct).
        assert len(ALL_TABS) == 21
        assert len(pc.TAB_RULES) == 21
        assert set(pc.CONFIG_TAB_TITLES) == set(ALL_TABS)

    def test_tab_nav_covers_all_21_tabs(self):
        """F6 (T-1752, ADR-1018-6 D1): nav-разметка исчерпывающа."""
        assert set(pc.TAB_NAV) == set(ALL_TABS)
        assert set(pc.TAB_NAV.values()) <= set(pc.NAV_TITLES)

    def test_nav_order_and_titles(self):
        # F1 (10.25, ADR-1025-1 D1/D2): «Память» — отдельный nav-раздел.
        # SUPERSEDE menu-freeze 10.20/10.21 (Human Gate §7).
        assert pc.NAV_ORDER == ("modules", "ai", "memory", "permsoc")
        assert pc.NAV_TITLES == {
            "modules": "Модули", "ai": "ИИ", "memory": "Память",
            "permsoc": "PERMsoc"}

    def test_tab_nav_helper(self):
        assert pc.tab_nav(TAB_PERMSOC) == "permsoc"
        assert pc.tab_nav(TAB_MOD_SLEEP) == "modules"
        # F1: memory_rag/chat_lore/relations уехали из «ИИ» в «Память».
        assert pc.tab_nav(TAB_CHAT_LORE) == pc.NAV_MEMORY
        assert pc.tab_nav(TAB_MEMORY_RAG) == pc.NAV_MEMORY
        assert pc.tab_nav(TAB_RELATIONS) == pc.NAV_MEMORY
        # «ИИ» сохранён: провайдеры/промпты/кэш/имена (ADR-1025-1 D1).
        assert pc.tab_nav(TAB_LLM_PROVIDERS) == pc.NAV_AI
        assert pc.tab_nav(TAB_PROMPTS) == pc.NAV_AI
        assert pc.tab_nav(TAB_SMART_CACHE) == pc.NAV_AI
        assert pc.tab_nav(TAB_PEOPLE_NAMES) == pc.NAV_AI
        assert pc.tab_nav(None) is None
        assert pc.tab_nav("unknown") is None

    def test_every_nav_has_sections(self):
        """F6 (D5): нет «мёртвых» nav/секций — каждая sec имеет ≥1 группу."""
        for tab in ALL_TABS:
            assert pc.tab_group_ids(tab), tab
        navs = {pc.tab_nav(t) for t in ALL_TABS}
        assert navs == set(pc.NAV_ORDER)

    def test_permsoc_title_drift_fixed(self):
        """F6 (T-1752, ADR-1018-6 D3): подпись = фактическому разделу."""
        assert pc.CONFIG_TAB_TITLES[TAB_PERMSOC] == "PERMsoc"

    def test_config_tab_titles_parity_with_js(self):
        """Инвариант: CONFIG_TAB_TITLES ↔ web/app.js TABS[].label (19)."""
        import re
        js = open("web/app.js", encoding="utf-8").read()
        pairs = dict(re.findall(
            r"\{ id: '(\w+)', icon: '[^']+', label: '([^']*)'", js))
        for tab in ALL_TABS:
            assert pairs.get(tab) == pc.CONFIG_TAB_TITLES[tab], tab

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
        # 90 GROUPS − 2 content (tab=None) = 88 mapped; 10.13 (F1+F2+F3+F8+F4):
        # REGISTRY 427; 10.14 (F1 anti-echo-self-reply): +2 (GRAPH_FACT_WEIGHT_BOT,
        # BOT_SELF_AWARENESS_ENABLED) → 429; 10.14 (F2 persona-storage-core):
        # +1 (PERSONA_ENABLED) → 430 (локальный Δ фичи).
        # 10.14 (F8 self-reflection-llm-provider): +4 (INTEL_REFLECTION_*) →
        # 434 (GROUPS/mapped/TAB_RULES без изменений).
        # 10.14 (F6 help-guide-integration): +1 PG-only content →
        # 436 = 435 + 1 env-only BETTERSTACK_HOST (ADR-1018-1 D3);
        # GROUPS/mapped/TAB_RULES без изменений.
        # 10.19 (F3/ADR-1019-3 D3, UPD3 п.5): +1 REGISTRY
        # (IMPORT_HISTORY_RETENTION_DAYS), +2 GROUPS (limits_chat_key/
        # limits_chat_context), +2 mapped, +2 TAB_RULES (mod_budgets;
        # 19→20) → 437/92/90/20.
        # 10.23 (F5/ADR-1023-5 D5): +5 REGISTRY, +3 GROUPS, +3 mapped
        # (models_images/keys_images → llm_providers; flags_module_images →
        # mod_direct) → 446/95/93; TAB_RULES 20 (новых вкладок нет).
        # 10.23 (F8/ADR-1023-8, review iter1): +10 REGISTRY (Stage-1/2 + режимы),
        # +1 GROUPS/mapped (prompts_verbilizer → вкладка prompts) → 457/96/94;
        # phantom-ключ content.dynamic_cliche_list НЕ регистрируем (review
        # iter1, Low: F4 хранит клише в PG-таблице, ключ был бы «мёртвой
        # ручкой»); TAB_RULES 20 — вкладок не добавляем.
        # 10.24 (F7/ADR-1024-3 D1): +1 REGISTRY (ANTICLICHE_MAX_PATTERNS),
        # +1 GROUPS/mapped (limits_anticliche → вкладка prompts) → 458/97/95;
        # TAB_RULES 20 — вкладок не добавляем.
        # 10.24 (F21/ADR-1024-22 D8): +1 REGISTRY (BUDGETS_ENABLED),
        # +1 GROUPS/mapped (flags_module_budgets → вкладка mod_budgets) →
        # 459/98/96; TAB_RULES 20 — вкладок не добавляем.
        # 10.24 (F5/ADR-1024-9 D3): Δ REGISTRY/GROUPS/_TAB_BY_GROUP = 0
        # (группа flags_module_images лишь меняет вкладку-владельца) →
        # 459/98/96; TAB_RULES 20→21 (+mod_images).
        assert len(pc._TAB_BY_GROUP) == 96
        assert len(GROUPS) == 98
        assert len(pc.REGISTRY) == 459


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
        # F5 (10.24, ADR-1024-9 D1): тумблер изображений ПЕРЕНЕСЁН из
        # «Прямых ответов» в отдельную вкладку — дублирования быть не должно.
        assert "flags_module_images" not in tab_group_ids(TAB_MOD_DIRECT)

    def test_mod_images_composition(self):
        """F5 (10.24, ADR-1024-9 D1): отдельная вкладка «Генерация
        изображений» — ровно одна группа flags_module_images, nav «Модули»."""
        assert tab_group_ids(TAB_MOD_IMAGES) == {"flags_module_images"}
        assert pc.tab_nav(TAB_MOD_IMAGES) == pc.NAV_MODULES
        assert pc.CONFIG_TAB_TITLES[TAB_MOD_IMAGES] == "Генерация изображений"
        # провайдер остаётся «одним домом» на llm_providers.
        assert "flags_module_images" not in tab_group_ids(TAB_LLM_PROVIDERS)

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
        # 10.19 (F3/D1): limits_worker переехал в «Бюджеты» (mod_budgets).
        groups = tab_group_ids(TAB_MOD_CHECKUP)
        assert groups == {
            "flags_service", "flags_throttle", "limits_checkup",
            "limits_service", "models_checkup",
            "keys_betterstack"}
        assert "limits_worker" not in groups
        assert "models_checkup" not in tab_group_ids(TAB_LLM_PROVIDERS)
        assert "keys_betterstack" not in tab_group_ids(TAB_LLM_PROVIDERS)

    def test_mod_budgets_composition(self):
        """F3 (D1) + F21 (10.24, ADR-1024-22 D1): «Бюджеты» — оба контура +
        лимит контекста + master-группа флагов."""
        assert tab_group_ids(TAB_MOD_BUDGETS) == {
            "flags_module_budgets",
            "limits_chat_key", "limits_chat_context", "limits_worker"}

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
    # F4 10.16: CSS-канон вынесен в app.css — маркеры = разметка+стили.
    HTML = (open("web/index.html", encoding="utf-8").read()
            + open("web/static/app.css", encoding="utf-8").read())

    def test_11_modules_in_js(self):
        for mid in ALL_TABS[:11]:
            assert "id: '%s'" % mid in self.JS, mid
        assert self.JS.count("mod_") >= 11

    def test_ia_v2_shell_markers(self):
        """F1 (T-2393, SUPERSEDE menu-freeze 10.20/10.21): введён раздельный
        app shell (ADR-1025-1 D6) — sidebar ≥1200, drawer 768–1199,
        bottom-nav <768. Legacy dead-menu токены по-прежнему запрещены."""
        for token in ("sidebarOpen", "MENU_ORDER", "MENU_LABELS"):
            assert token not in self.JS, token
        assert 'class="app-sidebar"' in self.HTML
        assert 'class="bottom-nav"' in self.HTML
        assert 'class="app-drawer"' in self.HTML
        # OFF-режим (IA_V2_ENABLED=false) сохраняет navbar-полосу.
        assert 'class="navbar-band' in self.HTML
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

    def test_matrix_nav_grouping_markers(self):
        """F6 (D4): фронт группирует матрицу по nav из backend-ответа."""
        assert "NAV_GROUP_ORDER" in self.JS
        assert "NAV_GROUP_TITLES" in self.JS
        assert "it.nav ||" in self.JS
        assert "nav.sections" in self.JS
        assert "nav.sections" in self.HTML
        assert "sec.groups" in self.HTML

    def test_matrix_nav_group_parity_with_backend(self):
        """B4-4 (ADR-1018-6 D1/D4): JS-зеркало NAV_GROUP_ORDER/
        NAV_GROUP_TITLES == backend NAV_ORDER/NAV_TITLES (parity-инвариант
        против дрейфа двух источников правды)."""
        import re
        m_order = re.search(r"NAV_GROUP_ORDER\s*=\s*\[([^\]]*)\]", self.JS)
        assert m_order, "NAV_GROUP_ORDER не найден в web/app.js"
        js_order = tuple(re.findall(r"'([^']+)'", m_order.group(1)))
        assert js_order == tuple(pc.NAV_ORDER)

        m_titles = re.search(r"NAV_GROUP_TITLES\s*=\s*\{([^}]*)\}", self.JS)
        assert m_titles, "NAV_GROUP_TITLES не найден в web/app.js"
        js_titles = dict(re.findall(r"(\w+)\s*:\s*'([^']*)'",
                                    m_titles.group(1)))
        assert js_titles == dict(pc.NAV_TITLES)

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
    # 10.13 (F3): + memory.deep_sleep_trigger (select) — sanctioned Δ.
    sel = [s for s in pc.REGISTRY.values() if s.widget == "select"]
    assert {s.pg_key for s in sel} == {
        "limits.chat_temperature_preset_default",
        "memory.deep_sleep_trigger",
        # 10.20 (БЛОК 5.1, О4 FINAL): «Часовой пояс чата» — sanctioned Δ (+1).
        "limits.chat_timezone",
        # 10.23 (F8/ADR-1023-8): режим Вербализатора по умолчанию — select.
        "prompts.verbilizer_default_mode",
    }
    for spec in sel:
        assert spec.select_options and spec.select_labels
        assert len(spec.select_options) == len(spec.select_labels)
    trigger = next(s for s in sel
                   if s.pg_key == "memory.deep_sleep_trigger")
    assert trigger.select_options == ("after_sleep", "fixed")
