"""F1 round 10.25 — инвентарь/покрытие IA (T-2402, spec §8.4).

Доказывает БЕЗ потери функционала:
  * Zаморозка каталога: множества `pg_key`/групп и `{group_id: tab_id}`
    совпадают с baseline-фикстурой (СРАВНЕНИЕ МНОЖЕСТВ, не размеров);
  * ни одна группа/параметр не потеряны и не сменили вкладку-владельца;
  * 100% `TABS` достижимы из IA v2 (NAV_ITEMS_V2 / HUBS_V2 / MODULES /
    ROUTE_TO_TAB) — «сирот» нет;
  * TAB_TO_ROUTE ↔ ROUTE_TO_TAB согласованы (нет висячих маршрутов).
"""
import json
import re
from pathlib import Path

from services import param_catalog as pc

ROOT = Path(__file__).resolve().parent.parent
BASELINE = json.loads(
    (ROOT / "tests" / "fixtures" / "round1025" / "catalog_baseline.json")
    .read_text(encoding="utf-8"))
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _block(name: str) -> str:
    """Срез исходника `var NAME = ...;` до закрывающей `};`/`];`."""
    start = APP_JS.index("var %s = " % name)
    ends = [i for i in (APP_JS.find("\n  };", start), APP_JS.find("\n  ];", start))
            if i != -1]
    return APP_JS[start:min(ends)]


def _tabs_ids() -> list[str]:
    tabs = _block("TABS")
    return re.findall(r"\{ id: '(\w+)'", tabs)


class TestCatalogFrozen:
    def test_registry_keys_unchanged(self):
        # Равенство МНОЖЕСТВ (spec §8.4 п.1): ни один pg_key не потерян/добавлен.
        assert set(pc.REGISTRY.keys()) == set(BASELINE["registry_keys"])
        assert len(pc.REGISTRY) == BASELINE["counts"]["REGISTRY"]

    def test_group_ids_unchanged(self):
        assert set(g.id for g in pc.GROUPS) == set(BASELINE["group_ids"])
        assert len(pc.GROUPS) == BASELINE["counts"]["GROUPS"]

    def test_group_tab_owner_unchanged(self):
        # Перенос nav НЕ меняет вкладку-владельца группы (spec §8.4 п.2).
        current = {g.id: pc.group_tab(g.id) for g in pc.GROUPS}
        assert current == BASELINE["group_tab"]

    def test_counters_unchanged(self):
        assert len(pc.REGISTRY) == BASELINE["counts"]["REGISTRY"] == 468
        assert len(pc.GROUPS) == BASELINE["counts"]["GROUPS"] == 100
        assert len(pc._TAB_BY_GROUP) == BASELINE["counts"]["_TAB_BY_GROUP"] == 98
        assert len(pc.TAB_RULES) == BASELINE["counts"]["TAB_RULES"] == 21


class TestIaMapCoverage:
    def test_no_orphan_tabs(self):
        """Каждый tab.id из TABS достижим из IA v2 (spec §8.4/T-2402)."""
        tabs = _tabs_ids()
        assert tabs, "TABS не распарсены"

        route_to_tab = dict(
            (r, t) for r, t in re.findall(
                r"'(#/[^']*)':\s*'(\w+)'", _block("ROUTE_TO_TAB")))
        nav_v2 = re.findall(r"route:\s*'(#/[^']*)'", _block("NAV_ITEMS_V2"))
        hub_tabs = re.findall(r"tab:\s*'(\w+)'", _block("HUBS_V2"))
        module_tabs = re.findall(r"tab:\s*'(\w+)'", _block("MODULES"))

        reachable = set(hub_tabs) | set(module_tabs)
        reachable |= {route_to_tab[r] for r in nav_v2 if r in route_to_tab}
        # oversight открывается карточкой Статуса (#/oversight).
        reachable |= {route_to_tab.get("#/oversight")}
        reachable.discard(None)

        orphans = [t for t in tabs if t not in reachable]
        assert not orphans, "Сироты вне IA v2: %s" % orphans

    def test_tab_to_route_keys_are_valid_routes(self):
        route_to_tab = set(re.findall(
            r"'(#/[^']*)':", _block("ROUTE_TO_TAB")))
        tab_to_route = dict(re.findall(
            r"(\w+):\s*'(#/[^']*)'", _block("TAB_TO_ROUTE")))
        assert tab_to_route, "TAB_TO_ROUTE не распарсен"
        for tab, route in tab_to_route.items():
            assert route in route_to_tab, (tab, route)
            assert route_to_tab and route, tab

    def test_route_to_tab_values_are_known_tabs(self):
        tabs = set(_tabs_ids()) | {"persona"}
        values = re.findall(r"'(#/[^']*)':\s*'(\w+)'", _block("ROUTE_TO_TAB"))
        for _route, tab in values:
            assert tab in tabs, tab
