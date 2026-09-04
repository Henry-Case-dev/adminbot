"""Эпик 04.09.2026 (3.5.1, FR-25/FR-27, AC-4.1/AC-4.2) — тест-аудит маппинга
групп → вкладок: каждая конфиг-группа ровно на одной вкладке; композиция
вкладок соответствует таблице 3.5.1.
"""
import pytest

from services import param_catalog as pc
from services.param_catalog import (
    CATEGORIES,
    GROUPS,
    TAB_LIMITS,
    TAB_LLM_PROVIDERS,
    TAB_MEMORY_RAG,
    TAB_PROMPTS,
    TAB_REACTIONS_TRIGGERS,
    group_tab,
    tab_group_ids,
)

CONFIG_CATEGORIES = ("models", "keys", "prompts", "limits", "flags", "reactions")

ALL_TABS = [TAB_LLM_PROVIDERS, TAB_PROMPTS, TAB_LIMITS, TAB_MEMORY_RAG,
            TAB_REACTIONS_TRIGGERS]


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
        """Категории-источники по таблице 3.5.1."""
        def cats(tab):
            return {rule[0] for rule in pc.config_tab_sources(tab)}

        assert cats(TAB_LLM_PROVIDERS) == {"models", "keys"}
        assert cats(TAB_PROMPTS) == {"prompts"}
        assert cats(TAB_LIMITS) == {"limits", "flags"}
        assert cats(TAB_MEMORY_RAG) == {"limits", "flags", "memory"}
        assert cats(TAB_REACTIONS_TRIGGERS) == {"reactions", "flags"}

    def test_composition_of_memory_rag_tab(self):
        """3.5.1/фаза 2 (T-755): «Память и RAG» = limits_memory +
        limits_graph + flags_memory + memory_infinite (категория memory —
        зеркало web/app.js)."""
        assert tab_group_ids(TAB_MEMORY_RAG) == {
            "limits_memory", "limits_graph", "flags_memory", "memory_infinite"}

    def test_composition_of_reactions_tab(self):
        """3.5.1: «Реакции и Триггеры» = все 13 групп reactions + flags_media."""
        reactions_groups = {g.id for g in GROUPS if g.category == "reactions"}
        assert len(reactions_groups) == 13
        assert reactions_groups <= tab_group_ids(TAB_REACTIONS_TRIGGERS)
        assert "flags_media" in tab_group_ids(TAB_REACTIONS_TRIGGERS)
        assert "reactions_word_reactions" in tab_group_ids(TAB_REACTIONS_TRIGGERS)

    def test_limits_tab_excludes_memory_groups(self):
        groups = tab_group_ids(TAB_LIMITS)
        assert {"limits_memory", "limits_graph"} <= \
            {g.id for g in GROUPS if g.category == "limits"}
        assert "limits_memory" not in groups
        assert "limits_graph" not in groups
        assert "flags_media" not in groups
        assert "flags_memory" not in groups
        # остальные limits-группы на вкладке
        limits = {g.id for g in GROUPS if g.category == "limits"}
        assert groups & limits == limits - {"limits_memory", "limits_graph"}

    def test_providers_tab_covers_all_models_and_keys(self):
        models = {g.id for g in GROUPS if g.category == "models"}
        keys = {g.id for g in GROUPS if g.category == "keys"}
        assert len(models) == 8                       # + models_video_summary
        assert tab_group_ids(TAB_LLM_PROVIDERS) >= models | keys
        assert tab_group_ids(TAB_LLM_PROVIDERS) == models | keys

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

    def test_widget_keyvalue_on_summary_aliases(self):
        spec = next(s for s in pc.REGISTRY.values()
                    if s.pg_key == "limits.summary_aliases")
        assert spec.widget == "keyvalue"
        others_with_widget = [s for s in pc.REGISTRY.values()
                              if s.widget not in ("", "keyvalue")]
        assert others_with_widget == []
