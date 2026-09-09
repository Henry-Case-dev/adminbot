"""Раунд 10.4 (D, T-1022 AC-B1) — покрытие config-вкладок базовыми группами.

Виртуальное состояние БЕЗ браузера: каталог (REGISTRY) → resolve_progressive_level
→ группы вкладки (TAB_RULES-зеркало сервера/app.js groupedForTab) → фильтр
пустых групп (BUG-5-семантика «(0)» не рендерится) → для КАЖДОЙ config-вкладки
существует ≥1 группа с basicItems > 0 (иначе вкладка-карточка выглядела бы
пустой даже после свёртки advanced по умолчанию — ремедиация D-2/D-3).

Эталон каталога (REGISTRY 383 / GROUPS 71 / Settings 359) не трогается —
тест только читает; таблица виртуальной переразметки фич C/E/A проверяется
ЭТИМ ЖЕ тестом (дельта basic-разметки меняет результат и обязана остаться
зелёной).
"""
import pytest

from services.param_catalog import (
    GROUPS,
    REGISTRY,
    TAB_RULES,
    _resolve_tab_groups,
    resolve_progressive_level,
)

CONFIG_TAB_IDS = [tab_id for tab_id, _rules in TAB_RULES]


def _tab_items(tab_id: str) -> list:
    """Спеки вкладки (зеркало app.js groupedForTab: категория → правило)."""
    out = []
    for category, rule in dict(TAB_RULES)[tab_id]:
        groups = _resolve_tab_groups(category, rule)
        for spec in REGISTRY.values():
            if spec.category != category or spec.group not in groups:
                continue
            out.append(spec)
    return out


def _basic_group_ids(tab_id: str) -> set[str]:
    """Группы вкладки с ≥1 basic-параметром (после переразметки)."""
    from collections import defaultdict
    by_group: dict[str, list] = defaultdict(list)
    for spec in _tab_items(tab_id):
        by_group[spec.group].append(spec)
    basic = set()
    for gid, specs in by_group.items():
        if any(resolve_progressive_level(s) == "basic" for s in specs):
            basic.add(gid)
    return basic


class TestProgressiveTabBasicCoverage:
    def test_every_config_tab_has_basic_group(self):
        """AC-B1: каждой config-вкладке ≥1 группа с basicItems > 0 —
        «вкладка выглядит пустой» структурно исключено (D-2/D-3)."""
        for tab_id in CONFIG_TAB_IDS:
            basic_groups = _basic_group_ids(tab_id)
            assert basic_groups, (
                f"вкладка {tab_id}: нет ни одной группы с basic-параметрами — "
                f"после свёртки advanced (D-1) карточки будут только "
                f"заголовками со свёрнутым «(N)»")

    def test_tab_rules_exist_for_all_config_tabs(self):
        """TAB-зеркало: все config-вкладки из каталога описаны TAB_RULES."""
        assert len(CONFIG_TAB_IDS) >= 5
        from services.param_catalog import CONFIG_TAB_TITLES
        for tab_id in CONFIG_TAB_IDS:
            assert tab_id in CONFIG_TAB_TITLES, tab_id

    def test_groups_catalog_has_ids_for_items(self):
        """Каждый параметр вкладки имеет группу из GROUPS (консистентность
        виртуального состояния; GROUPS 71 — эталон не трогаем)."""
        group_ids = {g.id for g in GROUPS}
        for tab_id in CONFIG_TAB_IDS:
            for spec in _tab_items(tab_id):
                assert spec.group in group_ids, (
                    f"{spec.pg_key}: неизвестная группа {spec.group!r}")
