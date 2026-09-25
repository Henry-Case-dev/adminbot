"""F23 (раунд 10.24, `budget-guardrails-round1024`) — защитные пин-инварианты
бюджетного контура после F20/F21/F22.

Задача F23 — не дать бюджетному регрессу вернуться (R2/F21, R3/F22 и сквозные
R16/R17/R18). Здесь собраны «страховочные» тесты поверх фич-тестов
(`test_budget_global_toggle_round1024`, `test_budget_data_repair_round1024`):

  T-2376 — пин каталога/TAB_RULES (точные значения рантайма) + проверка, что
           ключ `flags.budgets_enabled` и его `GroupSpec` ведут в существующую
           вкладку `mod_budgets`, и что Python-маппинг не разошёлся с JS-зеркалом;
  T-2377 — freeze-инвариант меню «Модули»: состав меню/вкладок заморожен,
           `tma-menu-freeze` для «Бюджетов» НЕ снят (новых вкладок/карточек нет),
           у `mod_budgets` лишь тумблер на существующей карточке;
  guard  — резолв master-флага (global/per-chat/fail-open ON), OFF → фон
           свободен и учёт ведётся, `manual-overrides-immutable`, read-only
           диагностика (`diag`/`audit-chat-overrides`), R16-аддитивность.

Δ каталога = 0, Δ DDL = 0: файл добавляет ТОЛЬКО тесты.
R17/R18: секреты не читаются/не цитируются; фикстуры синтетические.
"""
import asyncio
import re
from pathlib import Path

import pytest

from config.settings import settings
from services import budget_gate
from services import param_catalog as pc

# Общий харнесс F21/F22 — переиспользуем, а не дублируем (как F22 поверх F20).
from tests.test_budget_global_toggle_round1024 import (  # noqa: F401
    _FakeChatCacheByChat,
    _FakeHot,
    _FakePg,
    _setup,
)
from tests.test_budget_data_repair_round1024 import (  # noqa: F401
    SEED_ID,
    SEED_KEYS,
    fake_cp,
    _pg,
)

ROOT = Path(".")
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

# ── Закреплённые значения рантайма (сверены на baseline F23) ────────────────

EXPECTED_TAB_RULES_IDS = [
    "mod_summary", "mod_direct", "mod_factcheck", "mod_search",
    "mod_transcribe", "mod_video_summary", "mod_media_download", "mod_web",
    "mod_checkup", "mod_sleep", "mod_nostalgia", "mod_budgets", "mod_images",
    "llm_providers", "prompts", "memory_rag", "smart_cache", "people_names",
    "relations", "chat_lore", "permsoc",
]

# F5 (10.24) добавил 13-ю карточку (mod_images); F21 тумблер на существующей.
EXPECTED_MODULE_IDS = [
    "mod_summary", "mod_direct", "mod_factcheck", "mod_search",
    "mod_transcribe", "mod_video_summary", "mod_media_download", "mod_web",
    "mod_checkup", "mod_sleep", "mod_nostalgia", "mod_budgets", "mod_images",
]

# Витрина TABS (JS-порядок): 21 config-вкладка + 5 служебных
# (modules/access/status/info/oversight). Пинится СОСТАВ, не только число —
# иначе подмена вкладки при том же количестве проходит незамеченной
# (rev1/R1: детект мутации `oversight` → `oversight_evil`).
EXPECTED_TAB_IDS = [
    "llm_providers", "prompts", "mod_summary", "mod_direct", "mod_factcheck",
    "mod_search", "mod_transcribe", "mod_video_summary", "mod_media_download",
    "mod_web", "mod_checkup", "mod_sleep", "mod_nostalgia", "mod_budgets",
    "mod_images", "modules", "memory_rag", "smart_cache", "people_names",
    "relations", "permsoc", "access", "chat_lore", "status", "info",
    "oversight",
]

EXPECTED_BUDGET_GROUPS = {
    "flags_module_budgets",
    "limits_chat_key", "limits_chat_context", "limits_worker",
}


# ── Хелперы разбора JS-разметки ─────────────────────────────────────────────

def _js_tab_ids() -> list[str]:
    s = JS.index("var TABS = [")
    block = JS[s:JS.index("];", s)]
    return re.findall(r"\n    \{ id: '(\w+)',", block)


def _js_module_ids() -> list[str]:
    s = JS.index("var MODULES = [")
    block = JS[s:JS.index("];", s)]
    return re.findall(r"\n    \{ id: '(\w+)',", block)


def _js_tab_block(tab_id: str) -> str:
    s = JS.index("{ id: '%s', icon:" % tab_id)
    nxt = JS.find("{ id: '", s + 1)
    return JS[s:nxt]


def _js_module_block(module_id: str) -> str:
    s = JS.index("var MODULES = [")
    block = JS[s:JS.index("];", s)]
    for part in re.split(r"\n    \{ id: '", block)[1:]:
        if part.split("'", 1)[0] == module_id:
            return part
    raise AssertionError("карточка %s не найдена" % module_id)


def _js_tab_groups(tab_id: str) -> set[str]:
    block = _js_tab_block(tab_id)
    groups: set[str] = set()
    for chunk in re.findall(r"groups:\s*\[([^\]]*)\]", block):
        groups.update(re.findall(r"'([^']+)'", chunk))
    return groups


# ══ T-2376: пин каталога/TAB_RULES ═════════════════════════════════════════

class TestCatalogPins:
    """Точные значения каталога: любое несанкционированное Δ (ключ/группа/
    вкладка) валит пин — это и есть защита от регресса F21."""

    def test_registry_counts_pinned(self):
        assert len(pc.REGISTRY) == 473
        assert len(pc.GROUPS) == 102
        assert len(pc._TAB_BY_GROUP) == 100
        assert len(pc.TAB_RULES) == 21
        assert len(pc.TAB_NAV) == 21
        assert len(pc.CONFIG_TAB_TITLES) == 21

    def test_budgets_enabled_spec_pinned(self):
        spec = pc.get("BUDGETS_ENABLED")
        assert spec is not None
        assert spec.pg_key == "flags.budgets_enabled"
        assert spec.group == "flags_module_budgets"
        assert spec.category == pc.CATEGORY_FLAGS
        assert spec.type == "bool"
        assert pc.get_by_pg_key("flags.budgets_enabled") is spec
        # дефолт ON (обратная совместимость, ADR-1024-22 D2).
        assert settings.BUDGETS_ENABLED is True

    def test_budgets_group_pinned(self):
        group = pc.get_group("flags_module_budgets")
        assert group is not None
        assert group.category == pc.CATEGORY_FLAGS
        assert group.order == 21        # свободный слот, без коллизий (D8).

    def test_budgets_group_maps_to_existing_tab(self):
        assert pc.TAB_MOD_BUDGETS == "mod_budgets"
        assert pc.group_tab("flags_module_budgets") == pc.TAB_MOD_BUDGETS
        assert pc.tab_group_ids(pc.TAB_MOD_BUDGETS) == EXPECTED_BUDGET_GROUPS
        assert pc.tab_nav(pc.TAB_MOD_BUDGETS) == "modules"
        assert pc.CONFIG_TAB_TITLES[pc.TAB_MOD_BUDGETS] == "Бюджеты"

    def test_tab_catalog_snapshot_frozen(self):
        # Вкладки и их порядок: бюджетная фича НЕ создаёт новую вкладку.
        assert [rule[0] for rule in pc.TAB_RULES] == EXPECTED_TAB_RULES_IDS
        assert EXPECTED_TAB_RULES_IDS.count("mod_budgets") == 1


class TestNoCatalogDesync:
    """Синхронность Python-каталога и JS-зеркала (R2: «без рассинхрона»)."""

    def test_js_budget_tab_groups_match_python(self):
        assert _js_tab_groups("mod_budgets") == pc.tab_group_ids(
            pc.TAB_MOD_BUDGETS)

    def test_js_budget_tab_label_matches_python(self):
        block = _js_tab_block("mod_budgets")
        m = re.search(r"label: '([^']*)'", block)
        assert m and m.group(1) == pc.CONFIG_TAB_TITLES[pc.TAB_MOD_BUDGETS]

    def test_js_budget_card_toggle_pinned(self):
        block = _js_module_block("mod_budgets")
        assert "toggleKey: 'flags.budgets_enabled'" in block
        assert "tab: 'mod_budgets'" in block
        # F21: noToggle снят — карточка получила рабочий master-тумблер.
        assert "noToggle" not in block

    def test_python_flag_and_js_toggle_are_same_key(self):
        spec = pc.get("BUDGETS_ENABLED")
        assert "'%s'" % spec.pg_key in _js_module_block("mod_budgets")


# ══ T-2377: freeze-инвариант меню «Модули» ═════════════════════════════════

class TestMenuFreeze:
    """`tma-menu-freeze` не снят: карточка «Бюджеты» уже существовала, F21 лишь
    добавил тумблер. Новых пунктов/вкладок/карточек нет; состав и порядок
    витрины (`MODULES`/`TABS`) заморожен точными списками id.

    Глобальный freeze меню/каталога здесь — **осознанный frozen-contract**
    (см. `spec.md` §Frozen-contract): любое санкционированное изменение
    состава обязано обновить пины в том же коммите."""

    def test_modules_menu_composition_frozen(self):
        ids = _js_module_ids()
        assert len(ids) == 13
        assert ids == EXPECTED_MODULE_IDS
        assert len(ids) == len(set(ids))          # без дублей

    def test_tabs_menu_composition_frozen(self):
        ids = _js_tab_ids()
        # СОСТАВ и порядок (rev1: раньше пинилось только число — подмена
        # вкладки при count=26 проходила молча).
        assert ids == EXPECTED_TAB_IDS
        assert len(ids) == 26
        assert len(ids) == len(set(ids))
        assert ids.count("mod_budgets") == 1

    def test_budget_card_reuses_existing_tab_not_new_menu_item(self):
        # Карточка — та же существующая вкладка mod_budgets (не новый пункт).
        assert "tab: 'mod_budgets'" in _js_module_block("mod_budgets")
        assert _js_module_ids().index("mod_budgets") == (
            EXPECTED_MODULE_IDS.index("mod_budgets"))

    def test_budget_group_has_single_home(self):
        """`flags_module_budgets` живёт ровно на одной вкладке — и в JS, и в
        Python. Дублирование («два дома») поймано бы сразу."""
        js_homes = [t for t in _js_tab_ids()
                    if "flags_module_budgets" in _js_tab_groups(t)]
        assert js_homes == ["mod_budgets"]
        py_homes = [rule[0] for rule in pc.TAB_RULES
                    if "flags_module_budgets" in pc.tab_group_ids(rule[0])]
        assert py_homes == ["mod_budgets"]


# ══ Guard: резолв master-рубильника (fail-open ON) ═════════════════════════

class TestResolverGuard:
    @pytest.mark.asyncio
    async def test_default_on(self, monkeypatch):
        _setup(monkeypatch)                       # пустые слои → default True
        assert await budget_gate.budgets_enabled(None) is True
        assert await budget_gate.budgets_enabled(-100) is True

    @pytest.mark.asyncio
    async def test_global_off(self, monkeypatch):
        _setup(monkeypatch,
               hot_values={budget_gate.KEY_BUDGETS_ENABLED: False})
        assert await budget_gate.budgets_enabled(None) is False

    @pytest.mark.asyncio
    async def test_per_chat_override_wins(self, monkeypatch):
        import services.chat_params as cp
        import services.hot_config as hot
        monkeypatch.setattr(hot, "_cache", _FakeHot(
            {budget_gate.KEY_BUDGETS_ENABLED: False}))
        monkeypatch.setattr(cp, "_chat_params_cache", _FakeChatCacheByChat(
            {-100: {budget_gate.KEY_BUDGETS_ENABLED: True}}))
        assert await budget_gate.budgets_enabled(-100) is True   # chat ON
        assert await budget_gate.budgets_enabled(-200) is False  # global OFF

    @pytest.mark.asyncio
    async def test_fail_open_on_error(self, monkeypatch):
        async def _boom(*a, **kw):
            raise RuntimeError("pg down")

        monkeypatch.setattr("services.worker_settings.resolve_setting_cached",
                            _boom)
        assert await budget_gate.budgets_enabled(-100) is True


# ══ Guard: OFF → фон свободен, учёт ведётся ════════════════════════════════

class TestBackgroundFreeGuard:
    @pytest.mark.asyncio
    async def test_master_off_frees_background(self, monkeypatch):
        from services import worker_budget as wb
        _setup(monkeypatch,
               hot_values={budget_gate.KEY_BUDGETS_ENABLED: False})

        async def _usage(pg=None, scope=None, day=None):
            return [{"metric": wb.METRIC_CALLS, "used": 100, "limit": 0}]

        monkeypatch.setattr(wb, "get_usage", _usage)
        assert await wb.global_degradation_allows("dream") is True

    @pytest.mark.asyncio
    async def test_master_off_consume_allows_and_records(self, monkeypatch):
        from services import worker_budget as wb
        _setup(monkeypatch,
               hot_values={budget_gate.KEY_BUDGETS_ENABLED: False},
               overrides={wb.LIMIT_CALLS_PER_CHAT: 0})   # 0 = запрет при ON
        pg = _FakePg()
        assert await wb.consume(pg, "chat:-100", wb.METRIC_CALLS) is True
        # UPSERT выполнен до гейта — статистика не «слепнет» (ADR-1024-22 D4).
        assert pg.conn.rows[("chat:-100", "llm_calls")] == 1


# ══ Guard: manual-overrides-immutable ═══════════════════════════════════════

class TestManualOverridesImmutableGuard:
    @pytest.mark.asyncio
    async def test_plain_seed_keeps_manual_restores_absent(self, fake_cp):
        from services import chat_settings_seed as seed
        fake_cp.store[SEED_ID] = {
            "overrides": {
                "limits.chat_cooldown_seconds": 42,           # чужой ручной
                "limits.chat_global_key_budget_requests": 50,  # ручной seed
            },
            "meta": {"chat_settings_seed_version": 1},
        }
        await seed.apply_chat_settings_seed(_pg())
        overrides = fake_cp.store[SEED_ID]["overrides"]
        assert overrides["limits.chat_global_key_budget_requests"] == 50
        assert overrides["limits.chat_cooldown_seconds"] == 42
        assert overrides["limits.chat_context_budget_tokens"] == -1
        assert overrides["limits.chat_global_context_max_tokens"] == -1
        assert set(SEED_KEYS) <= set(overrides)


# ══ Guard: read-only диагностика (diag / audit-chat-overrides) ═════════════

class _ReadOnlyConn:
    def __init__(self):
        self.queries: list[str] = []

    async def fetchrow(self, sql, *args):
        self.queries.append(sql)
        return None

    async def fetch(self, sql, *args):
        self.queries.append(sql)
        return []


class _ReadOnlyPool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return _CM()


def _read_only_pg():
    from types import SimpleNamespace
    conn = _ReadOnlyConn()
    return SimpleNamespace(pool=_ReadOnlyPool(conn)), conn


class TestReadOnlyDiagnosticsGuard:
    def test_audit_chat_overrides_is_select_only(self):
        import manage
        pg, conn = _read_only_pg()
        asyncio.run(manage._collect_chat_overrides_audit(pg, chat_id=SEED_ID))
        assert conn.queries, "аудит не выполнил запросов"
        for sql in conn.queries:
            assert sql.lstrip().upper().startswith("SELECT")
        joined = " ".join(conn.queries).lower()
        for forbidden in ("insert ", "update ", "delete ", "pg_notify"):
            assert forbidden not in joined

    def test_diag_aliases_is_select_only(self):
        import manage
        pg, conn = _read_only_pg()
        asyncio.run(manage._collect_aliases_diag(pg, chat_ids=[SEED_ID]))
        assert conn.queries, "diag не выполнил запросов"
        for sql in conn.queries:
            assert sql.lstrip().upper().startswith("SELECT")
        joined = " ".join(conn.queries).lower()
        for forbidden in ("insert ", "update ", "delete ", "pg_notify"):
            assert forbidden not in joined


# ══ Guard: R16-аддитивность снимка бюджета ═════════════════════════════════

class TestR16SnapshotGuard:
    BASE_KEYS = {
        "day", "exceeded", "exceeded_metric", "used_calls", "limit_calls",
        "used_tokens", "limit_tokens", "unlimited", "forbidden", "source",
        "source_calls", "source_tokens",
    }

    @pytest.mark.asyncio
    async def test_snapshot_is_additive(self, monkeypatch):
        from services import chat_usage
        _setup(monkeypatch,
               hot_values={budget_gate.KEY_BUDGETS_ENABLED: False,
                           chat_usage.KEY_BUDGET_REQUESTS: 25,
                           chat_usage.KEY_BUDGET_TOKENS: 100000},
               used={chat_usage.METRIC_CALLS: 999,
                     chat_usage.METRIC_TOKENS: 999})
        snap = await chat_usage.budget_snapshot(object(), -100)
        # R16 — контракт АДДИТИВНЫЙ, а не «ровно один ключ»: базовый набор
        # обязан присутствовать целиком (rev1 Low: subset ловит и удаление,
        # и переименование любого базового ключа), а будущие санкционированные
        # аддитивные ключи не должны ронять страж.
        assert self.BASE_KEYS <= set(snap)
        assert "budgets_enabled" in snap       # аддитивный ключ F21 на месте
        assert snap["budgets_enabled"] is False
        # При OFF enforcement выключен, но статистика сохранена.
        assert snap["exceeded"] is False
        assert snap["used_calls"] == 999 and snap["limit_calls"] == 25


# ══ Guard: Δ DDL = 0 (бюджетный раунд не менял схему) ═══════════════════════

class TestDeltaZeroGuard:
    def test_ddl_statements_pinned(self):
        from services import pg_db
        # NOTE (A5, ADR-1026-17 D1): +1 (image_reservation — санкция
        # Δ DDL ≠ 0, verbatim §7 ADR); 45 → 46.
        assert len(pg_db.DDL_STATEMENTS) == 46

    def test_catalog_counts_unchanged_by_guardrails(self):
        # F23 — только тесты: значения совпадают с Δ F21 (D8).
        assert len(pc.REGISTRY) == 473
        assert len(pc.GROUPS) == 102
        assert len(pc._TAB_BY_GROUP) == 100
