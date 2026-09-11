"""Раунд 10.4 — бэкенд-добавления фич B/F/H/G (маркеры + юнит-касты).

G-2: _resolve_from_root усилен (мусор/NaN/inf → hot.get-фолбэк; валидные —
без изменений). B-12: build_alias_resolver (per-chat override → глобальные).
F/H: markers переносов (relations-вкладка, username-обогащение всем строк).
G: markers точек чтения (_chat_limit/_cp_g) + бэкфил-таблица.
"""
import asyncio

import pytest

from services import chat_params as cp_mod
from services.chat_params import get_chat_param, set_chat_params_cache
from services.summary_aliases import build_alias_resolver


# ── минимальный фейк кэша (как в test_chat_params) ───────────────────────

class _FakeCache:
    """ChatParamsCache-заглушка с фиксированным root."""

    def __init__(self, root: dict):
        self._root = root

    async def get_chat_params(self, chat_id: int) -> dict:
        return dict(self._root)

    async def get_chat_params_full(self, chat_id: int):
        return dict(self._root), None


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(cp_mod, "_chat_params_cache", None)
    yield
    monkeypatch.setattr(cp_mod, "_chat_params_cache", None)


def _root_with(overrides: dict) -> dict:
    return {"v": 1, "overrides": overrides, "gates": {}, "keys": {},
            "perm_overrides": {}, "meta": {}}


@pytest.mark.asyncio
async def test_g2_garbage_override_falls_back_to_hot(monkeypatch):
    """G-2: мусорный override (bool-ключ со строкой) → fallback hot.get."""
    monkeypatch.setattr(cp_mod, "_chat_params_cache",
                        _FakeCache(_root_with(
                            {"flags.chat_context_budgets_enabled": "мусор"})))
    monkeypatch.setattr("services.hot_config.get",
                        lambda key, default=None:
                        "FALLBACK_HOT" if key ==
                        "flags.chat_context_budgets_enabled" else default)
    value = await get_chat_param(-1, "flags.chat_context_budgets_enabled",
                                 "DEFAULT")
    assert value == "FALLBACK_HOT"


@pytest.mark.asyncio
async def test_g2_nan_float_falls_back_to_hot(monkeypatch):
    """G-2: NaN override для float-ключа → fallback (T-654-совместимость)."""
    monkeypatch.setattr(cp_mod, "_chat_params_cache",
                        _FakeCache(_root_with(
                            {"limits.chat_cooldown_ratio": float("nan")})))
    # возьмём заведомо float-ключ каталога: limits.cooldown_ratio может не
    # существовать — используем real float-ключ limits.lore_min_chars? нет —
    # определим по каталогу
    from services.param_catalog import REGISTRY
    float_key = next(s.pg_key for s in REGISTRY.values()
                     if s.type == "float" and s.category == "limits")
    monkeypatch.setattr(cp_mod, "_chat_params_cache",
                        _FakeCache(_root_with({float_key: float("nan")})))
    monkeypatch.setattr("services.hot_config.get",
                        lambda key, default=None:
                        75.0 if key == float_key else default)
    assert await get_chat_param(-1, float_key, 10.0) == 75.0


@pytest.mark.asyncio
async def test_g2_valid_override_still_wins(monkeypatch):
    """G-2-регресс: валидный override — как раньше (каст по каталогу)."""
    monkeypatch.setattr(cp_mod, "_chat_params_cache",
                        _FakeCache(_root_with(
                            {"limits.chat_cooldown_seconds": "42"})))
    monkeypatch.setattr("services.hot_config.get",
                        lambda key, default=None: 1)
    value = await get_chat_param(-1, "limits.chat_cooldown_seconds", 10.0)
    assert int(value) == 42


@pytest.mark.asyncio
async def test_b12_alias_resolver_override_then_global(monkeypatch):
    """B-12: per-chat override алиасов → пер-чат резолв; нет override →
    глобальные (наследование)."""
    monkeypatch.setattr(cp_mod, "_chat_params_cache", None)
    monkeypatch.setattr("services.hot_config.get",
                        lambda key, default=None:
                        '{"111": "Глобальное имя"}'
                        if key == "limits.summary_aliases" else default)
    # кэш пуст → глобальные алиасы
    r1 = await build_alias_resolver(-1)
    assert r1.resolve(111, "Ник", None) == "Глобальное имя"
    # override чата
    monkeypatch.setattr(cp_mod, "_chat_params_cache",
                        _FakeCache(_root_with(
                            {"limits.summary_aliases": {
                                "222": "Пер-чат имя"}})))
    r2 = await build_alias_resolver(222)
    assert r2.resolve(222, "Ник", "@ник2") == "Пер-чат имя"


# ── markers: точки чтения G (по файлам) ───────────────────────────────────

def test_g_read_points_markers():
    paths = {
        "services/summary_memory.py": "_chat_limit(",
        "services/summary_generator.py": "_chat_limit(",
        "services/direct_chat_service.py": "_cp_g(",
    }
    for path, marker in paths.items():
        src = open(path, encoding="utf-8").read()
        assert src.count(marker) >= 3, f"{path}: только {src.count(marker)}"


def test_g_backfill_table_keeps_edge_weight_global():
    """G-п.4 (таблица §4): edge_weight НЕ в бэкфиле (семантика графа);
    cap участников ≤ 300; R10.4-3: *TOKENS-ключи (Settings=None, tokens-
    режим выключен) исключены, живой charset-ключ треда (×2) — в таблице."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bf", "scripts/backfill_104_overrides.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert "limits.graph_edge_weight_increment" not in m.OVERRIDE_MULTIPLIERS
    assert m.OVERRIDE_MULTIPLIERS["limits.chat_map_participants_cap"][1] == 300
    assert len(m.OVERRIDE_MULTIPLIERS) == 15
    # R10.4-3: мёртвые tokens-ключи убраны, тред ×2 — через max_chars
    assert "limits.chat_thread_max_tokens" not in m.OVERRIDE_MULTIPLIERS
    assert "limits.chat_global_context_max_tokens" not in \
        m.OVERRIDE_MULTIPLIERS
    assert m.OVERRIDE_MULTIPLIERS["limits.chat_thread_max_chars"] == (2.0, None)


def test_f_relations_ui_markers():
    """F: вкладка relations (кастом-шаблон) + config-часть; блок участников
    в chat_lore удалён (негатив)."""
    html = open("web/index.html", encoding="utf-8").read()
    assert "activeTab === 'relations'" in html
    assert "groupedForTab(relationsTab())" in html
    assert "loadRelations(activeChatId)" in html
    js = open("web/app.js", encoding="utf-8").read()
    assert "relationsTab: function" in js
    assert "type: 'relations'" in js
    assert "label: 'Участники и отношения'" in js
    # негатив: в лоре участниковского блока нет (заменён подсказкой)
    assert "авто-стадии (SQLite-скоры)" not in html


def test_h_username_enrichment_markers():
    """H: username-обогащение ВСЕХ строк (Semaphore(5)); photo — топ-50."""
    src = open("web/api/chat_lore.py", encoding="utf-8").read()
    assert "asyncio.Semaphore(_RELATIONS_SEMAPHORE_LIMIT)" in src
    assert "_RELATIONS_SEMAPHORE_LIMIT = 5" in src
    assert "await asyncio.gather" in src
    assert "[:_RELATIONS_ENRICH_TOP]" in src          # photo-граница сохранена


# ═══ Ревью-фиксы раунда 10.4 (items 5-7) ═══════════════════════════════════

def test_g_dead_overrides_now_read_per_chat():
    """Ревью-фикс (G item 5): budget-база, level2, thread-лимиты переведены
    на per-chat чтение (бэкфил-ключи больше не write-only)."""
    src = open("services/direct_chat_service.py", encoding="utf-8").read()
    assert "budget_tokens = await _budget_gate(" in src
    assert "budget_tokens if budget_tokens is not None" in src
    assert "cap2 = int(await _cp_g(\n                                chat_id, \"limits.chat_level2_max_chars\"" in src
    assert "async def _thread_limit(self, chat_id: int)" in src
    assert "thread_limit=None" in src


def test_b13_points24_limitation_documented():
    """Item 7: ограничение B-13 points 2-4 зафиксировано комментарием в
    user_relations.py ('ОСОЗНАННОЕ ограничение')."""
    src = open("services/user_relations.py", encoding="utf-8").read()
    assert "ОСОЗНАННОЕ ограничение" in src
    assert "инжект" in src and "ГЛОБАЛЬНЫЕ алиасы" in src


def test_user_facing_text_updated():
    """Item 6: пользовательские описания обновлены («Модули»).
    10.9: мастер-тумблер описан в каталоге без старой подписи."""
    cat = open("services/param_catalog.py", encoding="utf-8").read()
    assert "Главный выключатель всех персонажей PERMsoc" in cat
    assert "вкладке «Модули и Фичи»" not in cat
    html = open("web/index.html", encoding="utf-8").read()
    assert 'class="module-list' in html
    assert "toggleModule(m, $event.target.checked)" in html
