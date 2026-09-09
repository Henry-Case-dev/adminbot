"""Эпик 04.09.2026 (3.5.1, FR-25/FR-27, AC-4.1/AC-4.2) — тест-аудит маппинга
групп → вкладок: каждая конфиг-группа ровно на одной вкладке; композиция
вкладок соответствует таблице 3.5.1.

Ре-дизайн 10.2 (BUG-3, spec §10 A/B): новая конфиг-вкладка «permsoc»
(TAB_PERMSOC): reactions_persons/reactions_permsoc + flags_permsoc +
limits_persons (переносы групп: kucha/alan_mimic в reactions_permsoc,
admin_id в reactions_admin, рубильники PERMsoc в flags_permsoc). 5 тестов
композиции актуализированы.
"""
import pytest

from services import param_catalog as pc
from services.param_catalog import (
    CATEGORIES,
    GROUPS,
    TAB_CHAT_LORE,
    TAB_LIMITS,
    TAB_LLM_PROVIDERS,
    TAB_MEMORY_DREAM,
    TAB_MEMORY_NOSTALGIA,
    TAB_MEMORY_RAG,
    TAB_MODULES_SWITCHES,
    TAB_PEOPLE_NAMES,
    TAB_PERMSOC,
    TAB_RELATIONS,
    TAB_PROMPTS,
    TAB_REACTIONS_TRIGGERS,
    group_tab,
    tab_group_ids,
)

CONFIG_CATEGORIES = ("models", "keys", "prompts", "limits", "flags", "reactions")

ALL_TABS = [TAB_LLM_PROVIDERS, TAB_PROMPTS, TAB_LIMITS, TAB_MEMORY_RAG,
            TAB_MEMORY_DREAM, TAB_MEMORY_NOSTALGIA,
            TAB_REACTIONS_TRIGGERS, TAB_PERMSOC, TAB_MODULES_SWITCHES,
            TAB_CHAT_LORE, TAB_PEOPLE_NAMES, TAB_RELATIONS]


class TestTabMappingAudit:
    def test_every_config_group_assigned_to_exactly_one_tab(self):
        seen = {}
        for g in GROUPS:
            if g.category not in CONFIG_CATEGORIES:
                continue
            tab = group_tab(g.id)
            assert tab is not None, f"группа {g.id} не приписана вкладке"
            assert tab in ALL_TABS
            seen.setdefault(tab, []).append(g.id)
        # все группы на месте и без дублей
        for tab, groups in seen.items():
            assert len(groups) == len(set(groups))

    def test_every_group_belongs_to_one_tab(self):
        by_tab = [set(tab_group_ids(t)) for t in ALL_TABS]
        union = set().union(*by_tab)
        for g in GROUPS:
            if g.category in CONFIG_CATEGORIES:
                assert g.id in union
        # никакая группа не лежит в двух вкладках
        for a in range(len(by_tab)):
            for b in range(a + 1, len(by_tab)):
                assert by_tab[a].isdisjoint(by_tab[b])

    def test_tab_sources_categories_match_table_351(self):
        """Категории-источники по таблице 3.5.1 + permsoc (spec §10 A)."""
        def cats(tab):
            return {rule[0] for rule in pc.config_tab_sources(tab)}

        assert cats(TAB_LLM_PROVIDERS) == {"models", "keys"}
        assert cats(TAB_PROMPTS) == {"prompts"}
        assert cats(TAB_LIMITS) == {"limits", "flags"}
        assert cats(TAB_MEMORY_RAG) == {"limits", "flags", "memory"}
        # раунд 10.4 (D-A1): триггеры — только reactions; permsoc —
        # reactions + flags + limits (F-канон порядка правил)
        assert cats(TAB_REACTIONS_TRIGGERS) == {"reactions"}
        assert cats(TAB_PERMSOC) == {"reactions", "flags", "limits"}
        assert cats(TAB_MODULES_SWITCHES) == {"flags"}
        assert cats(TAB_CHAT_LORE) == {"limits", "flags"}

    def test_composition_of_memory_rag_tab(self):
        """3.5.1/фаза 2 (T-755) + раунд 10.4 (C-2): «Память» =
        limits_memory + limits_graph + flags_memory + memory_infinite
        (dream/nostalgia вынесены на СВОИ вкладки — зеркало web/app.js)."""
        assert tab_group_ids(TAB_MEMORY_RAG) == {
            "limits_memory", "limits_graph", "flags_memory",
            "memory_infinite"}

    def test_composition_of_memory_dream_and_nostalgia_tabs(self):
        """Раунд 10.4 (C-2): «Сон» (memory_dream) и «Ностальгия»
        (memory_nostalgia) — ровно свои группы; категория memory покрыта
        целиком без дублей; зеркало TABS (web/app.js)."""
        assert tab_group_ids(TAB_MEMORY_DREAM) == {"memory_dream"}
        assert tab_group_ids(TAB_MEMORY_NOSTALGIA) == {"memory_nostalgia"}
        members = ({g.id for g in GROUPS if g.category == "memory"})
        assert members == {"memory_infinite", "memory_dream",
                           "memory_nostalgia"}
        js = open("web/app.js", encoding="utf-8").read()
        assert "id: 'memory_dream'" in js
        assert "id: 'memory_nostalgia'" in js
        assert "label: 'Сон'" in js
        assert "label: 'Ностальгия'" in js
        assert "label: 'Память'" in js
        assert "label: 'Память и RAG'" not in js

    def test_composition_of_reactions_tab(self):
        """Раунд 10.4 (D-A1 — канон): «Реакции и Триггеры» — ТОЛЬКО
        триггерные реакции {admin, summary, chat, memory}, без флагов."""
        assert tab_group_ids(TAB_REACTIONS_TRIGGERS) == {
            "reactions_admin", "reactions_summary", "reactions_chat",
            "reactions_memory"}
        assert "flags_media" not in tab_group_ids(TAB_REACTIONS_TRIGGERS)

    def test_composition_of_permsoc_tab(self):
        """Раунд 10.4 (D-A1 — канон): «Функции PERMsoc» = 11 реакционных
        групп (персоны+модули) + {flags_permsoc, flags_media} + 4 лимита;
        маркеры в зеркале TABS (web/app.js)."""
        assert tab_group_ids(TAB_PERMSOC) == {
            "reactions_persons", "reactions_permsoc", "reactions_deadpage",
            "reactions_mimic", "reactions_slavik", "reactions_alan",
            "reactions_olya", "reactions_war", "reactions_common",
            "reactions_goodmorning", "reactions_word_reactions",
            "flags_permsoc", "flags_media",
            "limits_persons", "limits_mimic", "limits_deadpage",
            "limits_media"}
        js = open("web/app.js", encoding="utf-8").read()
        assert "id: 'permsoc'" in js
        assert "Функции PERMsoc" in js
        assert "reactions_deadpage" in js
        assert "reactions_goodmorning" in js
        assert "reactions_word_reactions" in js
        assert "flags_media" in js
        assert "limits_mimic" in js

    def test_permsoc_tab_title_in_catalog(self):
        assert pc.CONFIG_TAB_TITLES[pc.TAB_PERMSOC] == "Функции PERMsoc"

    def test_limits_tab_excludes_memory_groups(self):
        """Раунд 10.4 (A-1): «Лимиты» исключают memory/graph/persons/mimic/
        deadpage/media/lore (ушли на permsoc/chat_lore); flags —
        memory/media/permsoc/modules/service/lore; flags_relations и
        limits_relations/limits_user_aliases остаются (фичи F/B — позже)."""
        groups = tab_group_ids(TAB_LIMITS)
        for gid in ("limits_memory", "limits_graph", "limits_persons",
                    "limits_mimic", "limits_deadpage", "limits_media",
                    "limits_lore", "limits_user_aliases", "limits_relations",
                    "flags_memory", "flags_media",
                    "flags_permsoc", "flags_modules", "flags_service",
                    "flags_lore", "flags_relations"):
            assert gid not in groups, gid
        # остальные limits-группы на вкладке
        limits = {g.id for g in GROUPS if g.category == "limits"}
        assert groups & limits == limits - {"limits_memory", "limits_graph",
                                            "limits_persons", "limits_mimic",
                                            "limits_deadpage", "limits_media",
                                            "limits_lore",
                                            "limits_user_aliases",
                                            "limits_relations"}
        assert "flags_chat_behavior" in groups                  # флаги на месте
        assert "flags_relations" not in groups                  # ушла на relations (F-1)
        assert "limits_relations" not in groups                 # ушла на relations (F-1)

    def test_modules_switches_and_lore_tabs_104(self):
        """Раунд 10.4 (A-7/A-1): «Модули (вкл/выкл)» = flags_modules +
        flags_service; лор-часть = limits_lore + flags_lore → 'chat_lore'."""
        assert tab_group_ids(TAB_MODULES_SWITCHES) == {
            "flags_modules", "flags_service"}
        assert group_tab("limits_lore") == TAB_CHAT_LORE
        assert group_tab("flags_lore") == TAB_CHAT_LORE
        assert pc.CONFIG_TAB_TITLES[TAB_MODULES_SWITCHES] == \
            "Модули (вкл/выкл)"
        assert pc.CONFIG_TAB_TITLES[TAB_CHAT_LORE] == "Лор чатов"
        js = open("web/app.js", encoding="utf-8").read()
        assert "id: 'modules_switches'" in js
        assert "label: 'Модули (вкл/выкл)'" in js
        assert "groups: ['limits_lore']" in js
        assert "groups: ['flags_lore']" in js

    def test_js_tabs_except_lists_match_backend(self):
        """Ре-дизайн 10.2+10.4 (BUG-3 + D-A1): зеркало TABS (web/app.js)
        содержит те же except-списки «Лимитов», что TAB_RULES:
        иначе regrouped-ключи рендерились бы и на «Лимитах»."""
        import re
        js = re.sub(r"\s+", " ", open("web/app.js", encoding="utf-8").read())
        # limits (категория limits): memory+graph+persons+mimic+deadpage+
        # media+lore в except
        assert "{ category: 'limits', except: ['limits_memory', " \
            "'limits_graph', 'limits_persons', 'limits_mimic', " \
            "'limits_deadpage', 'limits_media', 'limits_lore'] }" in js
        # limits (категория flags): memory+media+permsoc+modules+service+lore
        assert "{ category: 'flags', except: ['flags_memory', 'flags_media', " \
            "'flags_permsoc', 'flags_modules', 'flags_service', 'flags_lore'] " \
            "}" in js
        # sources-секции: permsoc-белые списки (зеркало TAB_RULES)
        assert "groups: [ 'reactions_persons', 'reactions_permsoc', " \
            "'reactions_deadpage', 'reactions_mimic', 'reactions_slavik', " \
            "'reactions_alan', 'reactions_olya', 'reactions_war', " \
            "'reactions_common', 'reactions_goodmorning', " \
            "'reactions_word_reactions']" in js
        assert "groups: [ 'limits_persons', 'limits_mimic', " \
            "'limits_deadpage', 'limits_media']" in js
        assert "groups: ['flags_modules', 'flags_service']" in js

    def test_providers_tab_covers_all_models_and_keys(self):
        models = {g.id for g in GROUPS if g.category == "models"}
        keys = {g.id for g in GROUPS if g.category == "keys"}
        assert len(models) == 8                       # + models_video_summary
        assert tab_group_ids(TAB_LLM_PROVIDERS) >= models | keys
        assert tab_group_ids(TAB_LLM_PROVIDERS) == models | keys

    def test_providers_tab_sections_104(self):
        """Раунд 10.4 (E-1/E-2): llm_providers — 4 секции (основные модели →
        ключи → фолбэк → расширенные); правила-порядок в TAB_RULES и зеркале
        TABS.sections; каждая группа — ровно на одной вкладке."""
        rules = pc.config_tab_sources(TAB_LLM_PROVIDERS)
        assert len(rules) == 5
        first = [g for c, g in [rules[0]]][0]
        assert rules[0][0] == "models"
        assert rules[0][1] == frozenset({"models_main"})
        assert rules[1][0] == "keys"
        assert rules[1][1] == frozenset(
            {"keys_llm", "keys_groq", "keys_openrouter"})
        assert rules[2][1] == frozenset({"models_fallback"})
        # секция «Расширенные»: 6 моделей + 4 ключа (без дублей)
        adv_models = rules[3][1]
        adv_keys = rules[4][1]
        assert len(adv_models) == 6 and len(adv_keys) == 4
        assert adv_models.isdisjoint(adv_keys)
        js = open("web/app.js", encoding="utf-8").read()
        assert "sectionTitle: function (grp)" in js
        assert "flatGroupRank: function (tab, category, groupId)" in js
        assert "title: 'Основные модели'" in js
        assert "title: 'Расширенные'" in js
        html = open("web/index.html", encoding="utf-8").read()
        assert "sectionTitle(grp)" in html
        # негатив: вкладки без sections — заголовков нет (рендер тот же)
        assert "sections: [" in js

    def test_providers_section4_has_basic_group(self):
        """Раунд 10.4 (E-4): секция «Расширенные» ≥1 basic-группа (свёрнутый
        аккордеон фичи D не прячет секцию); timeout/budget — advanced."""
        from services.param_catalog import resolve_progressive_level
        by_pg = {s.pg_key: s for s in pc.REGISTRY.values()}
        assert resolve_progressive_level(
            by_pg["models.llm_timeout"]) == "advanced"
        assert resolve_progressive_level(
            by_pg["models.llm_total_budget"]) == "advanced"
        # models_embeddings — базовый (видима на «Расширенных»)
        assert resolve_progressive_level(
            by_pg["models.embedding_model_name"]) == "basic"
        # каждая группа разметки: basic-ключ присутствует (AC-E3);
        # models_llm_timeouts — целиком advanced (таймауты/бюджеты — по E-4)
        from collections import defaultdict
        lvls = defaultdict(set)
        for s in pc.REGISTRY.values():
            if s.category == "models":
                lvls[s.group].add(resolve_progressive_level(s))
        for gid in ("models_main", "models_fallback", "models_embeddings",
                    "models_llm_guard", "models_extra_providers",
                    "models_video_summary", "models_checkup"):
            assert "basic" in lvls[gid], gid
        assert lvls["models_llm_timeouts"] == {"advanced"}

    def test_relocated_params_are_in_new_groups(self):
        """FR-26: окна/RAG-лимиты переехали группами (pg-ключи не тронуты)."""
        by_pg = {s.pg_key: s for s in pc.REGISTRY.values()}
        assert by_pg["limits.summary_window_hours"].group == "limits_memory"
        assert by_pg["limits.summary_max_window_messages"].group == "limits_memory"
        assert by_pg["limits.summary_rag_l2_limit"].group == "limits_graph"
        assert by_pg["limits.summary_rag_l3_limit"].group == "limits_graph"
        # доноры не опустели
        summary = {s.group for s in pc.REGISTRY.values()
                   if s.pg_key.startswith("limits.summary_")}
        assert "limits_summary" in summary

    def test_permsoc_group_moves(self):
        """BUG-3 (spec §10 B): переносы ключей — kucha/alan_mimic в
        reactions_permsoc, admin_id в reactions_admin, рубильники PERMsoc
        в flags_permsoc; pg-ключи/семантика НЕ тронуты."""
        by_pg = {s.pg_key: s for s in pc.REGISTRY.values()}
        assert by_pg["reactions.kucha_enabled"].group == "reactions_permsoc"
        assert by_pg["reactions.alan_mimic_enabled"].group == "reactions_permsoc"
        assert by_pg["reactions.admin_user_id"].group == "reactions_admin"
        assert by_pg["flags.permsoc_enabled"].group == "flags_permsoc"
        assert by_pg["flags.olya_enabled"].group == "flags_permsoc"
        assert by_pg["flags.mimic_enabled"].group == "flags_permsoc"
        # оставшиеся OLYA/mimic-forwards флаги — в flags_media
        assert by_pg["flags.olya_caption_enabled"].group == "flags_media"
        assert by_pg["flags.mimic_forwards_enabled"].group == "flags_media"
        assert by_pg["reactions.alan_user_id"].group == "reactions_persons"
        assert by_pg["limits.alan_reply_interval"].group == "limits_persons"

    def test_flat_order_matches_category_order_for_simple_tabs(self):
        """Раунд 10.4 (E-2, РЕГРЕСС-ЭТАЛОН): для вкладок без повторения
        категорий flat-rank == категориальный ранг (первый индекс правила) —
        порядок витрины limits/prompts/memory не изменился."""
        def first_indices(tab):
            first = {}
            for i, (category, _rule) in enumerate(pc.config_tab_sources(tab)):
                first.setdefault(category, i)
            return first
        for tab in (TAB_PROMPTS, TAB_LIMITS, TAB_MEMORY_RAG,
                    TAB_REACTIONS_TRIGGERS, TAB_PERMSOC):
            first = first_indices(tab)
            cats = list(first)
            assert cats == sorted(cats, key=lambda c: first[c]), tab

    def test_llm_providers_flat_order_104(self):
        """Раунд 10.4 (E-2): ожидаемый порядок витрины llm_providers —
        правила 1→4 (майн → ключи → фолбэк → расширенные модели+ключи),
        внутри — group.order; «Прочее» — в конец."""
        expected_first = [
            ("models", "models_main"), ("keys", "keys_llm"),
            ("keys", "keys_groq"), ("keys", "keys_openrouter"),
            ("models", "models_fallback"),
            ("models", "models_embeddings"),
        ]
        # flat-rank каждой группы == первое правило, где она перечислена
        rank_of = {}
        for i, (category, rule) in enumerate(pc.config_tab_sources(
                TAB_LLM_PROVIDERS)):
            assert isinstance(rule, frozenset)
            for gid in rule:
                rank_of.setdefault((category, gid), i)
        assert rank_of[expected_first[0]] == 0
        assert rank_of[expected_first[1]] == 1
        assert rank_of[expected_first[4]] == 2
        assert rank_of[expected_first[5]] == 3
        # keys "Расширенные" (rank 4) позже моделей «Расширенных» (rank 3)
        assert rank_of[("keys", "keys_search")] == 4

    def test_widget_keyvalue_on_summary_aliases(self):
        spec = next(s for s in pc.REGISTRY.values()
                    if s.pg_key == "limits.summary_aliases")
        assert spec.widget == "keyvalue"
        # Раунд 10.4 (B-7/B-8): допустимые виджеты "" | "keyvalue" | "select";
        # select — только temperature-пресет с опциями/подписями одной длины
        others_with_widget = [s for s in pc.REGISTRY.values()
                              if s.widget not in ("", "keyvalue", "select")]
        assert others_with_widget == []
        sel = [s for s in pc.REGISTRY.values() if s.widget == "select"]
        assert len(sel) == 1
        assert sel[0].pg_key == "limits.chat_temperature_preset_default"
        assert sel[0].select_options == ("precise", "balanced", "chatty")
        assert len(sel[0].select_options) == len(sel[0].select_labels)