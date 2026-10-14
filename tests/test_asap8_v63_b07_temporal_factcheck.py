"""ASAP 8 v6.3 B07 — Temporal: функция Фактчека, не карточка модуля.

Приёмка:
* B07.1 — в workspace Фактчека: gate `temporal.tool_enabled` (Settings-
  backed, hot), режимы contextual/current/historical/knowable-at-time,
  TTL вердиктов; UI — handoff (backend-резолвинг здесь);
* B07.2 — SEED_CATEGORIES включает CATEGORY_TEMPORAL (confirmed code
  cause) БЕЗ перетирания существующих PG owner-значений; отсутствующие
  Settings-backed ключи покрываются синтетикой config_cache; runtime-
  чтение дефолта — через hot (без дублей), POST/reload/restart/RBAC;
* B07.3 — factcheck_temporal отсутствует в выдаче карточек (top-level и
  subcard); backend `temporal_factcheck` + events/inspector сохранены;
  выключение Factcheck блокирует его функцию (tool fact_check) и не
  ломает обычный Direct.

TEST-LIFECYCLE: CONTRACT owner=REQ-B07 (temporal — функция Фактчека; сид
CATEGORY_TEMPORAL; gate на границе runtime)
TEST-LIFECYCLE: REGRESSION owner=REQ-B07 (temporal.tool_enabled не сиделся
и не читался из PG без рестарта; карточка-подмодуль в витрине)
"""
from __future__ import annotations

import asyncio
import json

import pytest

from config.settings import settings
from services import access as access_srv
from services import mca_gates
from services import module_registry as mr
from services import param_catalog as pc
from services import tool_schemas
from services.hot_config import get_config_cache, set_config_cache

pytestmark = pytest.mark.asap4


class _SettingsConn:
    """Мини- PG-conn с семантикой bot_settings: INSERT .. ON CONFLICT
    (key) DO NOTHING — как INSERT_SETTING_SQL в pg_db."""

    def __init__(self, rows=()):
        self.rows = {r["key"]: dict(r) for r in rows}
        self.queries: list[tuple[str, tuple]] = []

    async def execute(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        if "bot_settings" in sql and "INSERT" in sql:
            key, value, category = args
            if "DO UPDATE" in sql or key not in self.rows:
                # DO UPDATE (cache.set) — апсерт; DO NOTHING (сид) — только
                # если строки ещё нет.
                self.rows[key] = {"key": key, "value": json.loads(value),
                                  "category": category,
                                  "updated_at": ("now()" if "DO UPDATE"
                                                 in sql else None)}
        return "INSERT 0 1"

    async def fetch(self, sql, *args):
        if "bot_settings" in sql:
            return list(self.rows.values())
        return []


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        outer = self

        class _CM:
            async def __aenter__(self):
                return outer._conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


class _Pg:
    def __init__(self, conn):
        self.pool = _Pool(conn)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── B07.2: сид CATEGORY_TEMPORAL ────────────────────────────────────────────

class TestSeedTemporal:
    def test_seed_categories_include_temporal(self):
        from services.pg_db import SEED_CATEGORIES
        assert pc.CATEGORY_TEMPORAL in SEED_CATEGORIES

    def test_all_temporal_specs_are_seedable(self):
        """Каждый temporal-ключ каталога: категория сидируема, не секрет,
        Settings-field есть → `_seed_settings` его сидит из канона."""
        from services.pg_db import SEED_CATEGORIES
        temporal = [s for s in pc.REGISTRY.values()
                    if s.category == pc.CATEGORY_TEMPORAL]
        assert {"temporal.default_mode", "temporal.tool_enabled",
                "temporal.freshness_current_ttl_hours",
                "temporal.freshness_historical_ttl_hours"} == \
            {s.pg_key for s in temporal}
        for spec in temporal:
            assert spec.category in SEED_CATEGORIES
            assert not spec.secret
            assert spec.settings_field, spec.pg_key

    def test_seed_idempotent_owner_values_delta_zero(self):
        """Повторный сид НЕ перетирает существующие PG owner-значения
        (INSERT .. ON CONFLICT (key) DO NOTHING): Δowner-значений = 0."""
        from services.pg_db import (INSERT_SETTING_SQL, _seed_settings_into)
        owner_value = {"mode_owner": 1}      # значение владельца не трогаем
        conn = _SettingsConn(rows=[
            {"key": "temporal.tool_enabled", "value": owner_value,
             "category": "temporal", "updated_at": "2026-01-01"}])
        pg = _Pg(conn)

        async def scenario():
            await _seed_settings_into(conn)
            before = dict(conn.rows["temporal.tool_enabled"])
            await _seed_settings_into(conn)
            after = dict(conn.rows["temporal.tool_enabled"])
            return before, after

        before, after = _run(scenario())
        assert before["value"] == owner_value
        assert after == before, "owner-значение пережило повторный сид"
        assert "ON CONFLICT (key) DO NOTHING" in INSERT_SETTING_SQL

    def test_missing_settings_backed_temporal_synthesized(self):
        """config_cache: историческая БД без temporal-строк → /api/config
        получает честные Settings-дефолты (деривация на чтении, БД без
        записи), runtime-hot не затронут."""
        from services.config_cache import ConfigCache
        conn = _SettingsConn()
        cache = ConfigCache(pg=_Pg(conn), retry_attempts=1, retry_delay=0)
        snapshot = cache.get_all()
        assert snapshot["temporal.tool_enabled"] is \
            bool(settings.TEMPORAL_TOOL_ENABLED)
        assert snapshot["temporal.default_mode"] == \
            str(settings.TEMPORAL_DEFAULT_MODE)
        assert snapshot["temporal.freshness_current_ttl_hours"] == \
            settings.TEMPORAL_FRESHNESS_CURRENT_TTL_HOURS
        assert cache.get_updated_at("temporal.tool_enabled") is None, \
            "синтетический item — источник default, не persistent"


# ── B07.1/B07.2: POST → hot → runtime, restart, RBAC ────────────────────────

class TestGateLifecycle:
    def test_post_hot_read_runtime_tool_gate(self):
        """POST значения (ConfigCache.set) применяется без рестарта:
        hot-чтение gate'ом `fact_check`; до записи — честный Settings-дефолт
        (синтетика), после рестарта (новый кэш из PG) — persistent."""
        from services.config_cache import ConfigCache
        conn = _SettingsConn()
        set_config_cache(None)
        try:
            cache = ConfigCache(pg=_Pg(conn), retry_attempts=1, retry_delay=0)
            cache._pg_available = True        # пул инъекцией, PG «доступен»
            set_config_cache(cache)

            async def scenario():
                await cache.set("temporal.tool_enabled", False, "temporal")
                after_set = get_config_cache().get("temporal.tool_enabled")
                gate_after_set = tool_schemas._fact_check_tool_enabled()
                await cache.reload()          # reload из PG (персистентно)
                after_reload = get_config_cache().get("temporal.tool_enabled")
                return (after_set, gate_after_set, after_reload)

            after_set, gate_after_set, after_reload = _run(scenario())
            assert after_set is False
            assert gate_after_set is False
            assert after_reload is False
        finally:
            set_config_cache(None)
        # «Рестарт»: новый ConfigCache читает те же строки PG
        cache2 = ConfigCache(pg=_Pg(conn), retry_attempts=1, retry_delay=0)
        cache2._pg_available = True
        set_config_cache(cache2)
        try:
            _run(cache2.reload())
            assert get_config_cache().get("temporal.tool_enabled") is False
            assert tool_schemas._fact_check_tool_enabled() is False
        finally:
            set_config_cache(None)

    def test_select_modes_and_ttl_specs(self):
        """Режимы contextual/current/historical/knowable-at-time и TTL —
        каталоговые select/int на поверхности Фактчека (backend-резолв)."""
        mode = pc.get_by_pg_key("temporal.default_mode")
        assert mode.widget == "select"
        assert "contextual" in mode.select_options
        assert "knowable_at_time" in mode.select_options
        for key in ("temporal.freshness_current_ttl_hours",
                    "temporal.freshness_historical_ttl_hours"):
            spec = pc.get_by_pg_key(key)
            assert spec.type == "int"
            assert spec.group == "temporal_factcheck"
        from services.temporal_factcheck import resolve_requested_mode
        assert resolve_requested_mode(None, "contextual") == \
            ("contextual", False)

    def test_rbac_global_control_role_deny(self):
        """temporal.* — честный global control: per_chat=False (chat-SCOPE
        POST невозможен), редактирование — local_admin+; модератор/юзер —
        deny; global admin — allow."""
        spec = pc.get_by_pg_key("temporal.tool_enabled")
        assert spec.per_chat is False
        matrix = access_srv.default_matrix("temporal.tool_enabled")
        assert matrix["edit_roles"] == ["local_admin"]
        assert "moderator" in matrix["view_roles"]

        class _Ctx:
            is_global_admin = False
            is_dm_owner = False
            role_chat = "local_admin"      # chat-грант (F-7 §2.3)
            role_global = "user"
            rank = 3

        assert access_srv.can_edit_param(_Ctx(), matrix) is True
        _Ctx.role_chat = "moderator"
        _Ctx.rank = 2
        # moderator: view есть, edit-роли [local_admin] → deny
        assert access_srv.can_edit_param(_Ctx(), matrix) is False
        _Ctx.role_chat = "local_admin"
        _Ctx.rank = 3
        assert access_srv.can_edit_param(_Ctx(), matrix) is True

        class _Admin:
            is_global_admin = True
            is_dm_owner = False
            role_chat = None
            role_global = "global_admin"
            rank = 4

        assert access_srv.can_edit_param(_Admin(), matrix) is True

    def test_env_emergency_axis_still_works(self, monkeypatch):
        """env-ось K2/K1 остаётся аварийной AND-осью (не дублируется в
        каталоге); K1 OFF инертит tool независимо от каталога."""
        monkeypatch.setattr(type(settings), "MCA_TEMPORAL_FACTCHECK_ENABLED",
                            False)
        assert mca_gates.temporal_factcheck_tool_enabled() is False
        assert tool_schemas._fact_check_tool_enabled() is False


# ── B07.3: не карточка модуля; Factcheck OFF ≠ сломанный Direct ─────────────

class TestNotAModuleCard:
    def test_factcheck_temporal_absent_from_cards_output(self):
        data = {e["id"]: e for e in mr.registry_for_frontend()}
        assert "factcheck_temporal" not in data
        # backend-сервис/реестр/inspector живут
        assert "factcheck_temporal" in mr.MODULE_REGISTRY
        from services import temporal_factcheck as tf
        assert hasattr(tf, "resolve_requested_mode")
        assert "temporal.factcheck" in {
            getattr(d, "process_id", None)
            for d in __import__(
                "services.mca_process_registry",
                fromlist=["PROCESS_REGISTRY"]).PROCESS_REGISTRY}

    def test_no_new_top_level_card_added(self):
        top = [spec for spec in mr.MODULE_REGISTRY.values()
               if spec.parent_id is None
               and spec.classification == "product_module"]
        assert len(top) <= 12

    def test_factcheck_off_blocks_tool_not_direct(self):
        """Выключение Factcheck: tool fact_check скрыт (функция блокирована),
        Direct-триггер не зависит от factcheck-флагов (обычный Direct
        работает)."""
        direct_src = __import__("handlers.direct_chat", fromlist=["x"])
        import inspect
        src = inspect.getsource(direct_src._is_direct_trigger)
        assert "factcheck" not in src.lower()
        set_config_cache(None)
        try:
            # Factcheck OFF, temporal ON → tool скрыт
            class _Hot:
                def __init__(self, values):
                    self._values = values

                def get(self, key, default=None):
                    return self._values.get(key, default)
            set_config_cache(_Hot({
                "flags.factcheck_enabled": False,
                "temporal.tool_enabled": True}))
            assert tool_schemas._fact_check_tool_enabled() is False
            tools = tool_schemas.active_tools()
            assert "fact_check" not in [t["function"]["name"] for t in tools]
            # Factcheck ON + temporal ON → tool доступен (канон не сломан)
            set_config_cache(_Hot({
                "flags.factcheck_enabled": True,
                "temporal.tool_enabled": True}))
            tools = tool_schemas.active_tools()
            assert "fact_check" in [t["function"]["name"] for t in tools]
        finally:
            set_config_cache(None)

    def test_factcheck_handler_gate_reads_master_flag(self):
        """/factcheck — гейт модуля на границе исполнения (hot master)."""
        import handlers.factcheck as hf
        import inspect
        src = inspect.getsource(hf)
        assert 'hot.get("flags.factcheck_enabled"' in src
