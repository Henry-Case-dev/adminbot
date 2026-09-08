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
    TAB_LIMITS,
    TAB_LLM_PROVIDERS,
    TAB_MEMORY_RAG,
    TAB_PERMSOC,
    TAB_PROMPTS,
    TAB_REACTIONS_TRIGGERS,
    group_tab,
    tab_group_ids,
)

CONFIG_CATEGORIES = ("models", "keys", "prompts", "limits", "flags", "reactions")

ALL_TABS = [TAB_LLM_PROVIDERS, TAB_PROMPTS, TAB_LIMITS, TAB_MEMORY_RAG,
            TAB_REACTIONS_TRIGGERS, TAB_PERMSOC]


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
        assert cats(TAB_REACTIONS_TRIGGERS) == {"reactions", "flags"}
        assert cats(TAB_PERMSOC) == {"reactions", "flags", "limits"}

    def test_composition_of_memory_rag_tab(self):
        """3.5.1/фаза 2 (T-755) + раунд 9 (T-824/T-825, T-826/T-827): «Память
        и RAG» = limits_memory + limits_graph + flags_memory + категория
        memory целиком (memory_infinite + memory_dream + memory_nostalgia —
        зеркало web/app.js)."""
        assert tab_group_ids(TAB_MEMORY_RAG) == {
            "limits_memory", "limits_graph", "flags_memory",
            "memory_infinite", "memory_dream", "memory_nostalgia"}

    def test_composition_of_reactions_tab(self):
        """3.5.1 + BUG-3 (spec §10 B): «Реакции и Триггеры» = реакции кроме
        {reactions_persons, reactions_permsoc} + flags_media."""
        reactions_groups = {g.id for g in GROUPS if g.category == "reactions"}
        assert len(reactions_groups) == 15
        assert reactions_groups - {"reactions_persons", "reactions_permsoc"} \
            <= tab_group_ids(TAB_REACTIONS_TRIGGERS)
        assert "flags_media" in tab_group_ids(TAB_REACTIONS_TRIGGERS)
        assert "reactions_word_reactions" in tab_group_ids(TAB_REACTIONS_TRIGGERS)
        assert "reactions_admin" in tab_group_ids(TAB_REACTIONS_TRIGGERS)

    def test_composition_of_permsoc_tab(self):
        """Ре-дизайн 10.2, BUG-3 (spec §10 A/B): «Функции PERMsoc» =
        {reactions_persons, reactions_permsoc, flags_permsoc, limits_persons};
        маркеры в зеркале TABS (web/app.js)."""
        assert tab_group_ids(TAB_PERMSOC) == {
            "reactions_persons", "reactions_permsoc",
            "flags_permsoc", "limits_persons"}
        js = open("web/app.js", encoding="utf-8").read()
        assert "id: 'permsoc'" in js
        assert "Функции PERMsoc" in js
        assert "reactions_permsoc" in js
        assert "flags_permsoc" in js
        assert "limits_persons" in js

    def test_permsoc_tab_title_in_catalog(self):
        assert pc.CONFIG_TAB_TITLES[pc.TAB_PERMSOC] == "Функции PERMsoc"

    def test_limits_tab_excludes_memory_groups(self):
        groups = tab_group_ids(TAB_LIMITS)
        assert {"limits_memory", "limits_graph"} <= \
            {g.id for g in GROUPS if g.category == "limits"}
        assert "limits_memory" not in groups
        assert "limits_graph" not in groups
        assert "limits_persons" not in groups
        assert "flags_media" not in groups
        assert "flags_memory" not in groups
        assert "flags_permsoc" not in groups
        # остальные limits-группы на вкладке
        limits = {g.id for g in GROUPS if g.category == "limits"}
        assert groups & limits == limits - {"limits_memory", "limits_graph",
                                            "limits_persons"}

    def test_js_tabs_except_lists_match_backend(self):
        """Ре-дизайн 10.2 (BUG-3): зеркало TABS (web/app.js) содержит те же
        except-списки, что TAB_RULES (services/param_catalog.py): иначе
        regrouped-ключи (reactions_persons/reactions_permsoc, limits_persons,
        flags_permsoc) рендерились бы И на старых вкладках, И на permsoc."""
        js = open("web/app.js", encoding="utf-8").read()
        # reactions_triggers: реакции НЕ целиком (groups: null), а except —
        # персоны/permsoc ушли на вкладку «Функции PERMsoc»
        assert "{ category: 'reactions', except: ['reactions_persons', " \
            "'reactions_permsoc'] }" in js
        # limits (категория limits): memory+graph+persons в except
        assert "{ category: 'limits', except: ['limits_memory', " \
            "'limits_graph', 'limits_persons'] }" in js
        # limits (категория flags): memory+media+permsoc в except
        assert "{ category: 'flags', except: ['flags_memory', 'flags_media', " \
            "'flags_permsoc'] }" in js
        # permsoc-вкладка по-прежнему в белых списках (не исключена нигде)
        assert "groups: ['reactions_persons', 'reactions_permsoc']" in js
        assert "groups: ['flags_permsoc']" in js
        assert "groups: ['limits_persons']" in js

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

    def test_widget_keyvalue_on_summary_aliases(self):
        spec = next(s for s in pc.REGISTRY.values()
                    if s.pg_key == "limits.summary_aliases")
        assert spec.widget == "keyvalue"
        others_with_widget = [s for s in pc.REGISTRY.values()
                              if s.widget not in ("", "keyvalue")]
        assert others_with_widget == []