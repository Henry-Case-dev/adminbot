"""Редизайн 10.5 (T-1115) — parity smoke: каждый параметр (387) достижим.

Доказывает без потери фич:
  * каталог 387 параметров, каждый имеет группу и попадает на вкладку;
  * каждая конфиг-группа приписана ровно одной вкладке (TAB_RULES);
  * backend-матрица прав обходит ВСЕ параметры категорий (387);
  * hash-роутер покрывает все вкладки; hub-карточки ведут на валидные роуты;
  * navbar = ровно 6 секций эталона (§2.1).
"""
import re

from services import param_catalog as pc
from services.param_catalog import CATEGORIES, GROUPS, REGISTRY, group_tab

_JS = open("web/app.js", encoding="utf-8").read()
_HTML = open("web/index.html", encoding="utf-8").read()
_ACCESS = open("web/api/access.py", encoding="utf-8").read()

REFERENCE_SECTIONS = [
    ("status", "Статус"),
    ("how", "Как это работает"),
    ("modules", "Модули"),
    ("ai", "Настройки AI"),
    ("permsoc", "Функции PERMsoc"),
    ("access", "Доступы и Роли"),
]


def _catalog_specs():
    """Все категорийные параметры (category != None) — покрываются матрицей."""
    return [s for s in REGISTRY.values() if s.category is not None]


def _tabs_in(js_block: str) -> list[str]:
    return re.findall(r"(\w+):\s*'#/", js_block)


def _parse_block(name: str) -> str:
    start = _JS.index("var %s = " % name)
    ends = [i for i in (_JS.find("\n  };", start), _JS.find("\n  ];", start))
            if i != -1]
    return _JS[start:min(ends)]


class TestCatalogParity:
    def test_catalog_total_387(self):
        # REGISTRY 387 (вкл. infra/env-only) / GROUPS 74 / Settings 359.
        assert len(REGISTRY) == 387, len(REGISTRY)
        assert len(GROUPS) == 74
        from config.settings import Settings
        import dataclasses
        assert len({f.name for f in dataclasses.fields(Settings)}) == 359

    def test_every_param_has_group_and_reachable(self):
        for spec in _catalog_specs():
            assert spec.group, f"нет группы: {spec.pg_key}"
            if spec.category in ("models", "keys", "prompts", "limits",
                                 "flags", "reactions"):
                assert group_tab(spec.group) is not None, spec.group

    def test_every_group_assigned_to_a_tab(self):
        config_groups = [g for g in GROUPS
                         if g.category in ("models", "keys", "prompts",
                                           "limits", "flags", "reactions")]
        for g in config_groups:
            assert group_tab(g.id) is not None, g.id

    def test_matrix_covers_all_catalog_params(self):
        # backend матрицы обходит ВЕСЬ REGISTRY и пропускает только infra
        # (category None) — значит покрыты все 387.
        body = _ACCESS[_ACCESS.index("async def param_permissions_list"):]
        body = body[:body.index("async def param_permissions_put")]
        assert "for spec_key in sorted(REGISTRY)" in body
        assert "if spec.category is None:" in body
        assert '"group"' in body and '"title"' in body


class TestRouteParity:
    def test_route_covers_all_tabs(self):
        route_to_tab = _parse_block("ROUTE_TO_TAB")
        tab_to_route = _parse_block("TAB_TO_ROUTE")
        tab_ids = set(_tabs_in(tab_to_route))
        # каждая вкладка приложения (кроме не-роутовых) имеет маршрут
        for tab in ("status", "info", "oversight", "modules_feats",
                    "modules_switches", "reactions_triggers", "permsoc",
                    "llm_providers", "prompts", "limits", "memory_rag",
                    "memory_dream", "memory_nostalgia", "people_names",
                    "relations", "chat_lore", "access"):
            assert tab in tab_ids, tab
        # значения ROUTE_TO_TAB — только существующие вкладки
        values = re.findall(r"':\s*'(\w+)'", route_to_tab)
        for v in values:
            assert v in tab_ids, v

    def test_hub_cards_lead_to_valid_routes(self):
        route_to_tab = _parse_block("ROUTE_TO_TAB")
        valid_routes = set(re.findall(r"'(#/[^']*)':", route_to_tab))
        hubs = _parse_block("HUBS")
        card_routes = re.findall(r"route:\s*'(#/[^']*)'", hubs)
        assert card_routes, "hub-карточки не найдены"
        for r in card_routes:
            assert r in valid_routes, r

    def test_navbar_six_reference_sections(self):
        nav = _parse_block("NAV_ITEMS")
        pairs = re.findall(r"id:\s*'(\w+)',\s*label:\s*'([^']+)'", nav)
        assert pairs == REFERENCE_SECTIONS, pairs

    def test_hub_screens_present(self):
        hubs = _parse_block("HUBS")
        for route in ("'#/modules'", "'#/ai'", "'#/access'"):
            assert route in hubs, route
        assert "hubCards" in _JS and "hubCards" in _HTML


class TestScreenComposition:
    """T-1101..T-1112: каждый экран эталона имеет рендерер (tab-ветку или
    generic-конфиг). Параметры применяются через существующий конфиг-слой."""

    SCREEN_BRANCHES = ("currentTabIsConfig", "modules_feats", "oversight",
                       "access", "relations", "chat_lore", "status", "info")

    def test_all_screens_have_renderers(self):
        for branch in self.SCREEN_BRANCHES:
            assert branch in _HTML, branch

    def test_config_tabs_covered_by_generic_renderer(self):
        # все config-типы вкладок идут через один generic-шаблон по sources.
        config_tabs = ("llm_providers", "prompts", "limits", "memory_rag",
                       "memory_dream", "memory_nostalgia", "people_names",
                       "reactions_triggers", "modules_switches", "permsoc")
        for tab in config_tabs:
            assert ("id: '%s'" % tab) in _JS, tab
        assert "currentTabIsConfig" in _HTML
        assert "groupedForTab" in _JS


class TestNoOrphans:
    def test_tabs_md_parity_mapping_present(self):
        # TABS в app.js и TAB_RULES синхронны (см. test_frontend_tab_mapping).
        assert "MENU_ORDER" in _JS
        # Никакая вкладка TABS не осталась без route не-меню.
        tab_to_route = _parse_block("TAB_TO_ROUTE")
        for tab in ("chat_lore", "relations", "people_names",
                    "modules_feats", "modules_switches", "reactions_triggers",
                    "memory_dream", "memory_nostalgia"):
            assert ("%s:" % tab) in tab_to_route, tab

    def test_oversight_extras_kept(self):
        # фичи, которых нет в эталоне, обязаны остаться (T-1090).
        assert "'#/oversight'" in _JS
        assert "Oversight" in _HTML
