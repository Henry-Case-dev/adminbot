"""ASAP 7 F3 — Module Contract: реестр модулей + Initiative (§3.1–§3.3).

M1 — Initiative: карточка/вкладка существует, тумблер меняет requested,
effective совпадает с runtime-гейтом (env AND product), env-emergency OFF
отображается blocked (source=emergency_env), настройки реально влияют на
Intent service (hot, без рестарта), restart-семантика честная.

M4 — registry drift: каждый ProductModuleSpec обязан иметь master_param
(существующий ключ каталога), settings_groups ⊆ GROUPS, status_source,
help_anchor — иначе RED.

M2 — inventory: `mca_gates.KILL_SWITCHES` полностью маппится на registry
(MODULE_ENV_GATES) ИЛИ на явную INFRASTRUCTURE_RATIONALE-группу; 85 env-флагов
НЕ превращаются в чекбоксы.

TEST-LIFECYCLE: CONTRACT owner=asap7/F3
"""
import re
from pathlib import Path

import pytest

from config.settings import settings
from services import mca_gates
from services import mca_intents as mi
from services import module_registry as mr
from services import param_catalog as pc
from services.hot_config import set_config_cache

APP_JS = Path(__file__).resolve().parents[1] / "web" / "app.js"


class _FakeHot:
    """Подмена ConfigCache для product-оси (hot.get по ключу)."""

    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


@pytest.fixture()
def hot_with():
    """Фабрика: set/dict значений product-осей на время теста."""
    holder: dict = {}

    def _install(values):
        cache = _FakeHot(values)
        set_config_cache(cache)
        holder["cache"] = cache
        return cache

    yield _install
    set_config_cache(None)


# ═══ M4 — registry drift ═════════════════════════════════════════════════════

def test_m4_product_module_specs_are_complete():
    assert mr.MODULE_REGISTRY, "реестр пуст"
    for spec in mr.MODULE_REGISTRY.values():
        # master_param — существующий МИГРИРУЕМЫЙ ключ каталога (не выдуман)
        spec_entry = pc.get_by_pg_key(spec.master_param)
        assert spec_entry is not None, \
            f"{spec.id}: master_param {spec.master_param} вне каталога"
        assert spec_entry.migratable, \
            f"{spec.id}: master_param {spec.master_param} не migratable"
        # settings_groups ⊆ GROUPS
        group_ids = {g.id for g in pc.GROUPS}
        unknown = set(spec.settings_groups) - group_ids
        assert not unknown, f"{spec.id}: группы вне GROUPS: {unknown}"
        # непустые якоря статуса/справки
        assert spec.status_source, f"{spec.id}: пустой status_source"
        assert spec.help_anchor, f"{spec.id}: пустой help_anchor"
        # классификация/видимость из закрытых множеств
        assert spec.classification in ("product_module", "submodule",
                                       "infrastructure", "maintenance")
        assert spec.visibility in ("visible", "advanced", "hidden")
        assert spec.rationale, f"{spec.id}: пустой rationale"


def test_m4_initiative_tab_and_groups_wired():
    spec = mr.MODULE_REGISTRY["initiative"]
    assert spec.parent_id is None              # top-level карточка (§3.2)
    assert spec.master_param == "flags.initiative_enabled"
    assert set(spec.settings_groups) == {"flags_intent", "limits_intent"}
    # вкладка mod_initiative зарегистрирована в каноне каталога
    assert pc.CONFIG_TAB_TITLES.get("mod_initiative") == "Инициатива"
    assert pc.tab_nav("mod_initiative") == pc.NAV_MODULES
    assert pc.tab_group_ids("mod_initiative") == {"flags_intent",
                                                  "limits_intent"}
    for gid in spec.settings_groups:
        assert pc.group_tab(gid) == "mod_initiative"


def test_m4_intent_catalog_keys_shape():
    """9 ключей §3.2: 4 тумблера flags_intent + 5 лимитов limits_intent;
    pg_id человекочитаемые; дефолты — СУЩЕСТВУЮЩИЕ settings-атрибуты."""
    expected = {
        "MCA_INTENTS_ENABLED": ("flags.initiative_enabled", "flags_intent",
                                "bool", True),
        "MCA_INTENT_HEARTBEAT_ENABLED": ("flags.intent_heartbeat_enabled",
                                         "flags_intent", "bool", True),
        "MCA_INTENT_DECISION_ENABLED": ("flags.intent_decision_enabled",
                                        "flags_intent", "bool", True),
        "MCA_SEND_RECHECK_ENABLED": ("flags.send_recheck_enabled",
                                     "flags_intent", "bool", True),
        "MCA_INTENT_HEARTBEAT_BATCH_MAX": ("limits.intent_heartbeat_batch_max",
                                           "limits_intent", "int", 20),
        "MCA_INTENT_MAX_ATTEMPTS": ("limits.intent_max_attempts",
                                    "limits_intent", "int", 3),
        "MCA_INTENT_CANDIDATES_MAX": ("limits.intent_candidates_max",
                                      "limits_intent", "int", 8),
        "MCA_INTENT_RETENTION_DAYS": ("limits.intent_retention_days",
                                      "limits_intent", "int", 180),
        "MCA_INTENT_DEFER_BACKOFF_SECONDS": (
            "limits.intent_defer_backoff_seconds", "limits_intent", "int",
            1800),
    }
    for field, (pg_key, group, typ, _default) in expected.items():
        spec = pc.REGISTRY.get(field)
        assert spec is not None, f"{field} отсутствует в каталоге"
        assert spec.pg_key == pg_key
        assert spec.group == group
        assert spec.type == typ
        assert getattr(settings, field) == _default   # канон Settings не менялся


# ═══ M2 — inventory: KILL_SWITCHES → registry | rationale ════════════════════

def test_m2_kill_switches_fully_mapped():
    from services.mca_gates import KILL_SWITCHES
    owned: set[str] = set()
    for names in mr.MODULE_ENV_GATES.values():
        owned.update(names)
    rationalized: set[str] = set()
    for _cls, _rationale, names in mr.INFRASTRUCTURE_RATIONALE:
        dup = rationalized & set(names)
        assert not dup, f"дубль rationale-групп: {dup}"
        rationalized.update(names)
    overlap = owned & rationalized
    assert not overlap, f"одновременный owner+rationale: {overlap}"
    covered = owned | rationalized
    missing = set(KILL_SWITCHES) - covered
    assert not missing, f"kill-switches без owner/rationale: {sorted(missing)}"
    extra = covered - set(KILL_SWITCHES)
    assert not extra, f"мёртвые имена в маппинге: {sorted(extra)}"
    # env-гейты модулей реально читаются из settings (имя валидно)
    for module_id, gate in mr.ENV_GATES.items():
        assert module_id in mr.MODULE_REGISTRY
        assert gate in KILL_SWITCHES
        assert mr.ENV_GATES[module_id] == mr.ENV_GATES.get(module_id)


# ═══ §3.3 — effective_gate / гейты ═══════════════════════════════════════════

def test_effective_gate_defaults_on():
    """Инвариант аудита P7-C: при дефолтах effective ON, source=both —
    фича видима в «Модулях» (разрыв Module Contract закрыт)."""
    set_config_cache(None)          # hot не поднят → дефолты
    assert mr.effective_gate("initiative") == (True, True, "both")
    assert mca_gates.intents_enabled() is True
    assert mca_gates.intent_heartbeat_enabled() is True
    assert mca_gates.intent_decision_enabled() is True
    assert mca_gates.send_recheck_enabled() is True


def test_effective_gate_product_toggle_off(hot_with):
    hot_with({"flags.initiative_enabled": False})
    requested, effective, source = mr.effective_gate("initiative")
    assert (requested, effective, source) == (False, False, "product_toggle")
    # runtime-гейт совпадает с effective (M1)
    assert mca_gates.intents_enabled() is False
    # подгейты инертны при мастере OFF
    assert mca_gates.intent_heartbeat_enabled() is False
    assert mca_gates.intent_decision_enabled() is False
    assert mca_gates.send_recheck_enabled() is False


def test_effective_gate_env_emergency_off(monkeypatch):
    """env MCA_INTENTS_ENABLED=false → effective OFF, source=emergency_env;
    env важнее UI (даже при product ON)."""
    set_config_cache(None)
    monkeypatch.setattr(type(settings), "MCA_INTENTS_ENABLED", False)
    requested, effective, source = mr.effective_gate("initiative")
    assert (requested, effective, source) == (True, False, "emergency_env")
    assert mca_gates.intents_enabled() is False
    snap = mr.gate_snapshot("initiative")
    assert snap["env_enabled"] is False
    assert snap["source"] == "emergency_env"


def test_env_emergency_wins_over_product(hot_with, monkeypatch):
    hot_with({"flags.initiative_enabled": True})
    monkeypatch.setattr(type(settings), "MCA_INTENTS_ENABLED", False)
    assert mr.effective_gate("initiative")[1:] == (False, "emergency_env")


def test_k2_k4_subtoggles_env_and_product(hot_with, monkeypatch):
    """K2/K3/K4: каждая ось независима; env-emergency OFF душит подгейт
    даже при product ON; product OFF (hot) — без рестарта."""
    hot_with({"flags.intent_heartbeat_enabled": False,
              "flags.send_recheck_enabled": False})
    assert mca_gates.intent_heartbeat_enabled() is False
    assert mca_gates.intent_decision_enabled() is True
    assert mca_gates.send_recheck_enabled() is False
    # env-ось K3 OFF → K3 OFF (env важнее UI), K2/K4 не затронуты
    monkeypatch.setattr(type(settings), "MCA_INTENT_DECISION_ENABLED", False)
    assert mca_gates.intent_decision_enabled() is False
    monkeypatch.setattr(type(settings), "MCA_INTENT_DECISION_ENABLED", True)
    # env-ось K2 OFF → K2 OFF; K4 (product OFF) и K3 (обе ON) — по своим осям
    monkeypatch.setattr(type(settings), "MCA_INTENT_HEARTBEAT_ENABLED", False)
    assert mca_gates.intent_heartbeat_enabled() is False
    assert mca_gates.send_recheck_enabled() is False
    assert mca_gates.intent_decision_enabled() is True


# ═══ M1 — настройки реально влияют на Intent service (hot) ═══════════════════

def test_intent_limits_hot_and_clamped(hot_with):
    assert mca_gates.intent_heartbeat_batch_max() == 20
    assert mca_gates.intent_defer_backoff_seconds() == 1800
    hot_with({"limits.intent_heartbeat_batch_max": 5,
              "limits.intent_defer_backoff_seconds": 10,
              "limits.intent_max_attempts": 0})
    assert mca_gates.intent_heartbeat_batch_max() == 5     # hot применился
    assert mca_gates.intent_defer_backoff_seconds() == 60  # clamp ≥60
    assert mca_gates.intent_max_attempts() == 1            # clamp ≥1


@pytest.mark.asyncio
async def test_m1_intent_service_respects_product_toggle(hot_with):
    """M1: product-тумблер OFF → Intent service инертен (кандидат не
    создаётся) — настройки реально влияют на runtime, без рестарта."""
    hot_with({"flags.initiative_enabled": False})
    assert mi.candidate_from_trigger(trigger_kind="new_message",
                                     chat_id=-100500) is None
    hot_with({"flags.initiative_enabled": True})
    candidate = mi.candidate_from_trigger(trigger_kind="new_message",
                                          chat_id=-100500)
    assert candidate is not None and candidate.chat_id == -100500


@pytest.mark.asyncio
async def test_m1_status_snapshot_module_block(hot_with):
    """status.intents.module: requested/effective/source + heartbeat/поля
    страницы (аддитивно; существующие ключи не изменены)."""
    from services.status_service import StatusService
    hot_with({"flags.initiative_enabled": False})
    snap = await StatusService.intent_snapshot(
        StatusService(), chat_id=-100500, chat_scope_allowed=False)
    assert snap["state"] == "disabled"
    module = snap["module"]
    assert module["requested"] is False
    assert module["effective"] is False
    assert module["source"] == "product_toggle"
    assert module["heartbeat"]["restart_required_env"] is True
    # существующий контракт mca-12 сохранён
    for key in ("enabled", "state", "active", "top", "last_action"):
        assert key in snap

    hot_with({"flags.initiative_enabled": True})
    snap2 = await StatusService.intent_snapshot(
        StatusService(), chat_id=None, chat_scope_allowed=True)
    assert snap2["state"] == "restricted"
    assert snap2["module"]["effective"] is True
    assert snap2["module"]["source"] == "both"


# ═══ Фронт: registry → /api/config → MODULES ════════════════════════════════

def test_registry_for_frontend_shape():
    data = mr.registry_for_frontend()
    assert data and isinstance(data, list)
    entry = next(e for e in data if e["id"] == "initiative")
    assert entry["tab"] == "mod_initiative"
    assert entry["route"] == "#/modules/initiative"
    assert entry["master_param"] == "flags.initiative_enabled"
    assert entry["settings_groups"] == ["flags_intent", "limits_intent"]
    assert entry["classification"] == "product_module"


def test_js_module_card_registered():
    """JS-витрина содержит карточку mod_initiative (fallback-путь миграции
    §3.1), а реестр — каноническую запись initiative."""
    js = APP_JS.read_text(encoding="utf-8")
    assert "id: 'mod_initiative'" in js
    assert "toggleKey: 'flags.initiative_enabled'" in js
    assert "mod_initiative: ['overview', 'settings', 'limits']" in js
    # зеркала config-вкладки (TABS sources + порядок матрицы прав + иконка)
    assert "flags_intent" in js and "limits_intent" in js
    assert re.search(r"\{\s*id:\s*'mod_initiative',\s*icon:\s*'bolt'", js)
    assert "'mod_initiative'," in js      # TAB_SECTION_ORDER
    assert "mod_initiative: 'bolt'" in js  # TAB_ICON
    # merge-механика реестра присутствует (аддитивный путь для F4)
    assert "f3ApplyModuleRegistry" in js
    assert "data.modules" in js
