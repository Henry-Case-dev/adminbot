"""Раунд 10.19 (F3 budget-settings-section, T-1856…T-1860) — раздел
«Бюджеты», sentinel-поля, хук сида настроек и аддитивная «Сводка» (R16).

Покрытие:
  * каталог-Δ (санкция UPD3 п.5): 437/92/407/412/90/20; группы
    `limits_chat_key`/`limits_chat_context`; перенос `limits_worker` в
    `mod_budgets`; retention-ключ в `limits_memory`;
  * три семейства sentinel (`0`/`−1`/`>0`) для бюджетов/контекста/retention;
  * `build_summary.limits` — оба контура + контекст + хранение; аддитивность
    (старый `budget` сохранён); «Безлимит (∞)»/«Импорт: Вечно» на UI-слое;
  * `retention_policy` guard: `0` = вечно → purge запрещён;
  * JS-parity: нов; `budgetRatio` guard при `limit <= 0`; тумблер безлимита.

R17: значения секретов/ключей не используются.
"""
import re
from pathlib import Path

import pytest

from config.settings import Settings, settings
from services import budget_limits as bl
from services import chat_usage, retention_policy
from services import oversight
from services import param_catalog as pc

ROOT = Path(".")
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


# ── каталог-Δ ───────────────────────────────────────────────────────────────

class TestCatalogDeltaF3:
    def test_counts(self):
        import dataclasses
        # 10.24 (F21/ADR-1024-22 D8): +1 REGISTRY/Settings/categorized
        # (BUDGETS_ENABLED), +1 GROUPS/mapped (flags_module_budgets →
        # вкладка mod_budgets); TAB_RULES 20 — новых вкладок нет.
        assert len(pc.REGISTRY) == 459
        assert len(pc.GROUPS) == 98
        assert len(pc._TAB_BY_GROUP) == 96
        assert len(pc.TAB_RULES) == 20
        assert len(pc.TAB_NAV) == 20
        assert len({f.name for f in dataclasses.fields(Settings)}) == 418
        categorized = [s for s in pc.REGISTRY.values()
                       if s.category is not None]
        assert len(categorized) == 434

    def test_new_groups_exist(self):
        assert pc.get_group("limits_chat_key") is not None
        assert pc.get_group("limits_chat_context") is not None
        assert pc.group_tab("limits_chat_key") == pc.TAB_MOD_BUDGETS
        assert pc.group_tab("limits_chat_context") == pc.TAB_MOD_BUDGETS
        assert pc.group_tab("limits_worker") == pc.TAB_MOD_BUDGETS

    def test_budgets_tab_composition(self):
        # F21 (10.24, ADR-1024-22 D1): +master-группа флагов на той же вкладке.
        assert pc.tab_group_ids(pc.TAB_MOD_BUDGETS) == {
            "flags_module_budgets",
            "limits_chat_key", "limits_chat_context", "limits_worker"}
        assert pc.CONFIG_TAB_TITLES[pc.TAB_MOD_BUDGETS] == "Бюджеты"
        assert pc.tab_nav(pc.TAB_MOD_BUDGETS) == pc.NAV_MODULES

    def test_moved_groups(self):
        by_pg = {s.pg_key: s for s in pc.REGISTRY.values()}
        assert by_pg["limits.chat_global_key_budget_requests"].group == \
            "limits_chat_key"
        assert by_pg["limits.chat_global_key_budget_tokens"].group == \
            "limits_chat_key"
        for key in ("limits.chat_global_context_max_tokens",
                    "limits.chat_thread_max_tokens",
                    "limits.chat_context_budget_tokens"):
            assert by_pg[key].group == "limits_chat_context", key
        # в limits_chat_budgets остались только доли CHAT_BUDGET_*_RATIO
        # (+ flags.chat_context_budgets_enabled — рендер-группа флага,
        # не бюджетный лимит: исключение задокументировано в test_param_catalog).
        budgets = [s.pg_key for s in pc.REGISTRY.values()
                   if s.group == "limits_chat_budgets"]
        assert all(k.endswith("_ratio")
                   or k == "flags.chat_context_budgets_enabled"
                   for k in budgets), budgets
        # limits_worker больше не в «Диагностике»
        assert "limits_worker" not in pc.tab_group_ids(pc.TAB_MOD_CHECKUP)

    def test_retention_key_registered(self):
        spec = pc.get("IMPORT_HISTORY_RETENTION_DAYS")
        assert spec is not None
        assert spec.pg_key == "limits.import_history_retention_days"
        assert spec.group == "limits_memory"
        assert spec.category == pc.CATEGORY_LIMITS
        assert spec.type == "int"
        assert Settings().IMPORT_HISTORY_RETENTION_DAYS == 180
        assert spec.per_chat is True


# ── sentinel-семейства (три НЕ взаимозаменяемы) ──────────────────────────────

class TestSentinelsF3:
    def test_budget_sentinel(self):
        assert bl.budget_state(0) == "forbidden"
        assert bl.budget_state(-1) == "unlimited"
        assert bl.budget_state(100) == "cap"

    def test_context_sentinel(self):
        assert bl.context_state(0) == "unset"
        assert bl.context_state(-1) == "unlimited"
        assert bl.context_state(5000) == "cap"

    def test_retention_sentinel(self):
        assert bl.retention_state(0) == "eternal"
        assert bl.retention_state(180) == "cap"
        assert bl.retention_state(-1) == "invalid"

    def test_families_differ(self):
        assert bl.budget_state(0) != bl.retention_state(0)
        assert bl.context_state(0) != bl.retention_state(0)


# ── retention_policy guard (0 = вечно → purge запрещён) ─────────────────────

class TestRetentionPolicy:
    @pytest.mark.asyncio
    async def test_zero_is_eternal_purge_forbidden(self, monkeypatch):
        async def _resolve(key, *, chat_id=None, default=None):
            return 0, "chat"
        monkeypatch.setattr("services.worker_settings."
                            "resolve_setting_with_source", _resolve)
        allowed, days, source = await retention_policy.imported_history_purge_allowed(-100)
        assert allowed is False
        assert days == 0
        assert source == "chat"

    @pytest.mark.asyncio
    async def test_positive_allows(self, monkeypatch):
        async def _resolve(key, *, chat_id=None, default=None):
            return 30, "chat"
        monkeypatch.setattr("services.worker_settings."
                            "resolve_setting_with_source", _resolve)
        allowed, days, source = await retention_policy.imported_history_purge_allowed(-100)
        assert allowed is True
        assert days == 30

    @pytest.mark.asyncio
    async def test_negative_invalid_falls_back_to_default(self, monkeypatch):
        async def _resolve(key, *, chat_id=None, default=None):
            return -5, "chat"
        monkeypatch.setattr("services.worker_settings."
                            "resolve_setting_with_source", _resolve)
        allowed, days, source = await retention_policy.imported_history_purge_allowed(-100)
        assert allowed is True
        assert days == 180
        assert source == "default"

    @pytest.mark.asyncio
    async def test_resolve_error_fail_closed(self, monkeypatch):
        """D-5 (ревью Батча C): ошибка резолва → fail-CLOSED (purge запрещён)
        — безопасный дефолт для разрушительной операции."""
        async def _boom(*a, **kw):
            raise RuntimeError("pg down")
        monkeypatch.setattr("services.worker_settings."
                            "resolve_setting_with_source", _boom)
        allowed, days, source = await retention_policy.imported_history_purge_allowed(-100)
        assert allowed is False
        assert days == 0
        assert source == "error"


# ── build_summary.limits (аддитивно, R16) ───────────────────────────────────

def _fake_key_status(unlimited=False):
    def metric(limit):
        return {"used": 3, "limit": limit,
                "unlimited": bl.is_unlimited(limit),
                "forbidden": bl.is_forbidden(limit),
                "source": "chat" if limit < 0 else "global"}
    return {"calls": metric(-1 if unlimited else 100),
            "tokens": metric(-1 if unlimited else 500000)}


class TestLimitsBlock:
    @pytest.mark.asyncio
    async def test_limits_structure_and_unlimited(self, monkeypatch):
        async def _key_status(pg, chat_id):
            return _fake_key_status(unlimited=True)

        async def _resolve(key, *, chat_id=None, default=None):
            if key == "limits.chat_global_context_max_tokens":
                return -1, "chat"
            if key == "limits.chat_thread_max_tokens":
                return 3000, "global"
            if key == "limits.chat_context_budget_tokens":
                return 4000, "default"
            if key == "limits.import_history_retention_days":
                return 0, "chat"
            return default, "default"

        monkeypatch.setattr(chat_usage, "key_status", _key_status)
        monkeypatch.setattr("services.worker_settings."
                            "resolve_setting_with_source", _resolve)
        day_rows = [{"metric": "llm_calls", "used": 5, "limit": -1},
                    {"metric": "llm_tokens", "used": 10, "limit": -1}]
        limits = await oversight._limits_block(object(), -100, day_rows)
        assert limits["key_budget"]["calls"]["unlimited"] is True
        assert limits["worker_budget"]["calls"]["limit"] == -1
        assert limits["worker_budget"]["tokens"]["unlimited"] is True
        assert limits["context"]["global_tokens"]["unlimited"] is True
        assert limits["context"]["thread_tokens"]["limit"] == 3000
        assert limits["storage"]["import_forever"] is True
        assert limits["storage"]["label"] == "Вечно"

    @pytest.mark.asyncio
    async def test_direct_contour_reads_key_status(self, monkeypatch):
        """D-1 (ревью Батча C): key_budget читает ФАКТИЧЕСКИ direct-контур
        (`chat_usage.key_status`), а не зеркало worker-строк."""
        seen: list[int] = []

        async def _key_status(pg, chat_id):
            seen.append(chat_id)
            return {
                "calls": {"used": 7, "limit": 100, "unlimited": False,
                          "forbidden": False, "source": "chat"},
                "tokens": {"used": 11, "limit": 500000, "unlimited": False,
                           "forbidden": False, "source": "global"},
            }

        async def _resolve(key, *, chat_id=None, default=None):
            return default, "default"

        monkeypatch.setattr(chat_usage, "key_status", _key_status)
        monkeypatch.setattr("services.worker_settings."
                            "resolve_setting_with_source", _resolve)
        # Разные источники: key_status (7/11) vs day_rows (5/9) — контуры
        # НЕ должны совпадать (иначе D-1: key_budget == worker_budget).
        day_rows = [{"metric": "llm_calls", "used": 5, "limit": 60},
                    {"metric": "llm_tokens", "used": 9, "limit": 300000}]
        limits = await oversight._limits_block(object(), -100, day_rows)
        assert seen == [-100], \
            "S10.19-15: chat_usage.key_status вызван РОВНО один раз на чат"
        assert limits["key_budget"]["calls"]["used"] == 7
        assert limits["key_budget"]["tokens"]["used"] == 11
        assert limits["key_budget"]["calls"]["limit"] == 100
        assert limits["worker_budget"]["calls"]["used"] == 5
        assert limits["worker_budget"]["tokens"]["used"] == 9
        assert limits["key_budget"]["calls"] != limits["worker_budget"]["calls"]
        assert limits["key_budget"]["tokens"] != limits["worker_budget"]["tokens"]

    @pytest.mark.asyncio
    async def test_context_unset_returns_effective_default(self, monkeypatch):
        """D-6 (ревью Батча C): `0`/None (не задано) → эффективный дефолт
        (F4: 5000/3000), а не ложный `limit: 0`."""
        async def _key_status(pg, chat_id):
            return _fake_key_status()

        async def _resolve(key, *, chat_id=None, default=None):
            if key == "limits.chat_global_context_max_tokens":
                return 0, "chat"            # явный 0 = «не задано»
            if key == "limits.chat_thread_max_tokens":
                return None, "default"      # env не задан
            return default, "default"

        monkeypatch.setattr(chat_usage, "key_status", _key_status)
        monkeypatch.setattr("services.worker_settings."
                            "resolve_setting_with_source", _resolve)
        limits = await oversight._limits_block(object(), -100, [])
        assert limits["context"]["global_tokens"]["limit"] == 5000
        assert limits["context"]["global_tokens"]["source"] == "default"
        assert limits["context"]["thread_tokens"]["limit"] == 3000
        assert limits["context"]["total_budget_tokens"]["limit"] == \
            oversight.CONTEXT_LIMIT_KEYS[2][3]

    @pytest.mark.asyncio
    async def test_storage_cap_label(self, monkeypatch):
        async def _key_status(pg, chat_id):
            return _fake_key_status(unlimited=False)

        async def _resolve(key, *, chat_id=None, default=None):
            if key == "limits.import_history_retention_days":
                return 90, "chat"
            return default, "default"

        monkeypatch.setattr(chat_usage, "key_status", _key_status)
        monkeypatch.setattr("services.worker_settings."
                            "resolve_setting_with_source", _resolve)
        limits = await oversight._limits_block(object(), -100, [])
        assert limits["storage"]["import_forever"] is False
        assert limits["storage"]["import_retention_days"] == 90
        assert limits["storage"]["label"] == "90 дней"

    @pytest.mark.asyncio
    async def test_invalid_override_negative_default_no_minus_label(
            self, monkeypatch):
        """D-2.6 (Low, ревью итерации 4): невалидный override И негативный
        `STORAGE_DEFAULT` → нормализованный fallback (180), label без
        «-N дней» (единый источник истины `retention_policy`)."""
        async def _key_status(pg, chat_id):
            return _fake_key_status()

        async def _resolve(key, *, chat_id=None, default=None):
            if key == "limits.import_history_retention_days":
                return -1, "chat"            # мусорный override
            return default, "default"

        monkeypatch.setattr(chat_usage, "key_status", _key_status)
        monkeypatch.setattr("services.worker_settings."
                            "resolve_setting_with_source", _resolve)
        monkeypatch.setattr(oversight, "STORAGE_DEFAULT", -1)
        monkeypatch.setattr(retention_policy, "_FALLBACK_DAYS", 180)
        limits = await oversight._limits_block(object(), -100, [])
        assert limits["storage"]["import_retention_days"] == 180
        assert limits["storage"]["import_forever"] is False
        assert limits["storage"]["label"] == "180 дней"
        assert "-1 дней" not in limits["storage"]["label"]

    @pytest.mark.asyncio
    async def test_fail_open_on_source_error(self, monkeypatch):
        async def _boom(*a, **kw):
            raise RuntimeError("pg down")

        monkeypatch.setattr(chat_usage, "key_status", _boom)
        monkeypatch.setattr("services.worker_settings."
                            "resolve_setting_with_source", _boom)
        limits = await oversight._limits_block(object(), -100, [])
        # Fail-open ПО-ПОД-ОБЪЕКТНО (R16, 500 не бывает): упавший
        # direct-источник (`key_status`) → `key_budget` отсутствует;
        # S10.19-14: worker-лимит при пустом дне — из настроек (не ложный 0 →
        # «Запрещено»); context/storage — с дефолтами.
        assert "key_budget" not in limits
        assert limits["worker_budget"]["calls"]["limit"] == \
            settings.WORKER_DAILY_LLM_CALLS_PER_CHAT
        assert limits["worker_budget"]["calls"]["forbidden"] is False
        assert "context" in limits and "storage" in limits

    @pytest.mark.asyncio
    async def test_additive_budget_key_preserved(self, monkeypatch):
        # build_summary сохраняет старый `budget` (worker) — проверяем через
        # прямой вызов _limits_block: он НЕ трогает `budget`.
        async def _key_status(pg, chat_id):
            return _fake_key_status()

        async def _resolve(key, *, chat_id=None, default=None):
            return default, "default"

        monkeypatch.setattr(chat_usage, "key_status", _key_status)
        monkeypatch.setattr("services.worker_settings."
                            "resolve_setting_with_source", _resolve)
        limits = await oversight._limits_block(object(), -100, [])
        assert set(limits) == {"key_budget", "worker_budget", "context",
                               "storage"}


# ── config_migrations S10.19-8 ──────────────────────────────────────────────

class TestGlobalBudgetMigration:
    class _Cache:
        def __init__(self, values):
            self.values = dict(values)
            self.pg_available = True

        def get(self, key, default=None):
            return self.values.get(key, default)

        async def set(self, key, value, category):
            self.values[key] = value

    @pytest.mark.asyncio
    async def test_migrates_only_prev_defaults(self):
        from services import config_migrations as cm
        cache = self._Cache({
            "limits.chat_global_key_budget_requests": 25,
            "limits.chat_global_key_budget_tokens": 100000,
            "limits.worker_daily_llm_calls_per_chat": 35,
            "limits.worker_daily_llm_tokens_per_chat": 100000,
        })
        report = await cm.migrate_global_budget_defaults(cache)
        assert report == {
            "limits.chat_global_key_budget_requests": "updated",
            "limits.chat_global_key_budget_tokens": "updated",
            "limits.worker_daily_llm_calls_per_chat": "updated",
            "limits.worker_daily_llm_tokens_per_chat": "updated",
        }
        assert cache.values["limits.chat_global_key_budget_requests"] == 100
        assert cache.values["limits.chat_global_key_budget_tokens"] == 500000
        assert cache.values["limits.worker_daily_llm_calls_per_chat"] == 60
        assert cache.values["limits.worker_daily_llm_tokens_per_chat"] == 300000

    @pytest.mark.asyncio
    async def test_keeps_custom_and_new(self):
        from services import config_migrations as cm
        cache = self._Cache({
            "limits.chat_global_key_budget_requests": 777,   # кастом
            "limits.chat_global_key_budget_tokens": 500000,  # уже новый
        })
        report = await cm.migrate_global_budget_defaults(cache)
        assert report == {}
        assert cache.values["limits.chat_global_key_budget_requests"] == 777


# ── JS-parity / UI-маркеры ──────────────────────────────────────────────────

class TestJsParityF3:
    def test_mod_budgets_tab_in_js(self):
        assert "id: 'mod_budgets'" in JS
        assert "label: 'Бюджеты'" in JS
        assert "'limits_chat_key'" in JS and "'limits_chat_context'" in JS
        # mod_checkup больше не содержит limits_worker
        start = JS.index("id: 'mod_checkup'")
        checkup = JS[start:JS.index("id: 'mod_sleep'", start)]
        assert "limits_worker" not in checkup

    def test_budget_ratio_guard(self):
        block = JS[JS.index("budgetRatio: function (pair)"):
                   JS.index("budgetRatio: function (pair)") + 400]
        assert "pair.limit <= 0" in block
        assert "pair.unlimited" in block

    def test_unlimited_labels_and_toggle(self):
        assert "Безлимит (∞)" in JS
        assert "Запрещено" in JS
        assert "Импорт: " in JS
        assert "toggleBudgetsUnlimited" in JS
        assert "budgetsUnlimitedActive" in JS
        assert "toggleBudgetsUnlimited" in HTML

    def test_toggle_off_uses_explicit_defaults(self):
        # D-3 (ревью Батча C): OFF-ветка не делает DELETE (терял
        # meta.chat_settings_seed_version → сид переприменял −1) — пишет явные
        # значения глобального слоя (`global_value`) через POST.
        start = JS.index("toggleBudgetsUnlimited: async function")
        block = JS[start:start + 1600]
        assert "global_value" in block
        assert "method: 'DELETE'" not in block

    def test_storage_badge_in_oversight(self):
        assert "storageLabel(c.limits.storage)" in HTML
        # таблица использует новый limits-объект
        assert "c.limits && c.limits.key_budget" in HTML
        assert "limitsPairText(c.limits.key_budget.calls)" in HTML

    def test_no_negative_limit_text(self):
        # «5/-1» в разметке больше нет (текст через limitsPairText).
        assert "{{ c.budget.calls.used }}/{{ c.budget.calls.limit }}" not in HTML
