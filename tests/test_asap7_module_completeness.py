"""ASAP 7 F4 — Module completeness: остальные orphans (§3.2, аудит P7-C-5).

M2-расширение — все перенесённые operator-facing gates (stories/episodes,
character/self-model, random, experience) имеют owner-запись реестра
(MODULE_ENV_GATES) ИЛИ rationale; KILL_SWITCHES покрыты без пропусков, дублей
и мёртвых имён; каждый НОВЫЙ каталоговый тумблер реально прочитан runtime-
гейтом (нет «мёртвых ручек»).

M3 — parent submodules: own settings group (⊆ GROUPS, на поверхности
родителя), own effective state (effective_gate: env AND product), no orphan
controls (группа подмодуля не содержит чужих ключей).

M4 (drift) — новая ProductModuleSpec без обязательных полей → RED
(validate_spec); «no master» легален только с явным rationale.

Точечные соседи (mca12 stories / mca18 self-model / mca16 experience /
mca10 random) прогоняются отдельно — этот файл их контракт не дублирует.

TEST-LIFECYCLE: CONTRACT owner=asap7/F4
"""
from pathlib import Path

import pytest

from config.settings import settings
from services import mca_gates
from services import module_registry as mr
from services import param_catalog as pc
from services.hot_config import set_config_cache

APP_JS = Path(__file__).resolve().parents[1] / "web" / "app.js"
INDEX_HTML = Path(__file__).resolve().parents[1] / "web" / "index.html"

F4_MODULE_IDS = ("stories", "character", "experience", "random")

# §3.2: parent-поверхности подмодулей (родителей-карточек не создаём —
# «не делать 100 top-level карточек» §4.2).
F4_PARENTS = {
    "stories": "memory",
    "character": "persona",
    "experience": "memory",
    "random": "memory",
}

# Поверхность подмодуля — СУЩЕСТВУЮЩАЯ config-вкладка (новых вкладок нет).
F4_CONFIG_TABS = {
    "stories": "memory_rag",     # «Память»
    "character": "permsoc",      # PERMsoc (Advanced)
    "experience": "memory_rag",  # «Память»
    "random": "mod_sleep",       # «Сон» (дом memory_random)
}

# Новые каталоговые оси §3.2: env-атрибут → pg_key (product-ось, AND-гейт).
F4_CATALOG_AXES = {
    # stories/episodes (6)
    "MCA_STORIES_VITRINA_ENABLED": "flags.stories_vitrina_enabled",
    "MCA_STORIES_MANAGE_ENABLED": "flags.stories_manage_enabled",
    "MCA_EPISODES_ENABLED": "flags.episodes_enabled",
    "MCA_EPISODES_COMPILER_FACADE_ENABLED":
        "flags.episodes_compiler_facade_enabled",
    "MCA_EPISODES_CONTINUATION_ENABLED": "flags.episodes_continuation_enabled",
    "MCA_EPISODES_BACKFILL_ENABLED": "flags.episodes_backfill_enabled",
    # character (7)
    "MCA_SELF_MODEL_ENABLED": "flags.self_model_enabled",
    "MCA_TRAIT_RULES_ENABLED": "flags.trait_rules_enabled",
    "MCA_LEGACY_TRAITS_MIGRATION_ENABLED":
        "flags.legacy_traits_migration_enabled",
    "MCA_CHARACTER_LAYERS_ENABLED": "flags.character_layers_enabled",
    "MCA_CHARACTER_SPEECH_ENABLED": "flags.character_speech_enabled",
    "MCA_STYLE_SCOPE_ENABLED": "flags.style_scope_enabled",
    "MCA_POSTPROCESS_FORM_GUARD_ENABLED":
        "flags.postprocess_form_guard_enabled",
}

# Группа → owner-подмодуль (no orphan controls: в группе только свои ключи).
F4_GROUP_OWNER = {
    "flags_stories": "stories",
    "flags_character": "character",
    "memory_experience": "experience",
    "memory_random": "random",
}


class _FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


@pytest.fixture()
def hot_with():
    holder: dict = {}

    def _install(values):
        set_config_cache(_FakeHot(values))
        holder["cache"] = True
        return values

    yield _install
    set_config_cache(None)


# ═══ M2-расширение — inventory/ownership ═════════════════════════════════════

def test_m2_ext_new_modules_own_their_gates():
    """Каждая перенесённая ось F4 принадлежит ровно одной registry-записи;
    покрытие KILL_SWITCHES остаётся полным (без дублей/мёртвых имён)."""
    from services.mca_gates import KILL_SWITCHES
    owned: set[str] = set()
    for module_id, names in mr.MODULE_ENV_GATES.items():
        assert module_id in mr.MODULE_REGISTRY, module_id
        for name in names:
            assert name not in owned, f"дубль ownership: {name}"
            owned.add(name)
    rationalized: set[str] = set()
    for _cls, _rationale, names in mr.INFRASTRUCTURE_RATIONALE:
        dup = (rationalized | owned) & set(names)
        assert not dup, f"дубль rationale/owner: {dup}"
        rationalized.update(names)
    assert set(KILL_SWITCHES) - owned - rationalized == set()
    assert (owned | rationalized) - set(KILL_SWITCHES) == set()


def test_m2_ext_f4_axes_mapped():
    """Оси F3-rationale «submodule→F4» перенесены в owner-мэппинг, а не
    потеряны; Vision (вне объёма F4) остаётся rationale."""
    owned: set[str] = set()
    for names in mr.MODULE_ENV_GATES.values():
        owned.update(names)
    for env_name in F4_CATALOG_AXES:
        assert env_name in owned, f"{env_name} без owner-модуля"
    rationale_names: set[str] = set()
    for _cls, _r, names in mr.INFRASTRUCTURE_RATIONALE:
        rationale_names.update(names)
    assert "MCA_VISION_ENABLED" in rationale_names
    for env_name in F4_CATALOG_AXES:
        assert env_name not in rationale_names


def test_m2_ext_no_dead_knobs():
    """Обратный аудит: каждый НОВЫЙ каталоговый тумблер реально прочитан
    runtime-гейтом mca_gates (AND-гейт §3.3) — «мёртвых ручек» нет."""
    gates_src = " ".join(
        Path(mca_gates.__file__).read_text(encoding="utf-8").split())
    for env_name, pg_key in F4_CATALOG_AXES.items():
        spec = pc.get_by_pg_key(pg_key)
        assert spec is not None, f"{pg_key} вне каталога"
        assert spec.settings_field == env_name, (
            f"{pg_key}: default-ось должна быть существующим settings-атрибутом"
        )
        assert getattr(settings, env_name) is True  # канон Settings не менялся
        assert f'_module_catalog_flag("{pg_key}", True)' in gates_src, (
            f"{pg_key}: тумблер не прочитан runtime-гейтом (мёртвая ручка)"
        )
        # env-ось остаётся отдельной аварийной осью в гейте
        assert f'getattr(settings, "{env_name}", True)' in gates_src


def test_m2_ext_experience_random_no_settings_duplication():
    """Experience/Random: настройки УЖЕ есть — F4 не дублирует storage
    (нет новых ParamSpec на эти оси; группы существуют до F4)."""
    for pg_key in ("memory.experience_learning_enabled",
                   "memory.random_exploration_probability",
                   "memory.random_fallback_to_pseudorandom",
                   "keys.random_quantum_api_key"):
        spec = pc.get_by_pg_key(pg_key)
        assert spec is not None, f"{pg_key} отсутствует (не тот контур?)"
        assert spec.group in ("memory_experience", "memory_random",
                              "keys_random")
    # группа random.uses* — в memory_random (mca-10b), не задублирована
    uses = [s for s in pc.REGISTRY.values()
            if (s.pg_key or "").startswith("memory.random_uses_")]
    assert uses and all(s.group == "memory_random" for s in uses)


# ═══ M3 — parent submodules ══════════════════════════════════════════════════

def test_m3_parent_model_and_surfaces():
    for module_id in F4_MODULE_IDS:
        spec = mr.MODULE_REGISTRY[module_id]
        assert spec.classification == "submodule"
        assert spec.parent_id == F4_PARENTS[module_id]
        # поверхность — существующая config-вкладка родителя (новых нет)
        assert spec.config_tab == F4_CONFIG_TABS[module_id]
        assert spec.config_tab in pc.CONFIG_TAB_TITLES
        # own settings group: ⊆ GROUPS и отображена на вкладку поверхности
        for gid in spec.settings_groups:
            assert pc.group_tab(gid) == spec.config_tab, (
                f"{module_id}: группа {gid} не на поверхности родителя")
        assert pc.tab_nav(spec.config_tab) is not None


def test_m3_own_settings_groups_no_orphan_controls():
    """В группе подмодуля — только СВОИ ключи (паттерн Initiative §3.2)."""
    allowed = {
        "flags_stories": set(F4_CATALOG_AXES.values()) - {
            # character-оси живут в своей группе
            "flags.self_model_enabled", "flags.trait_rules_enabled",
            "flags.legacy_traits_migration_enabled",
            "flags.character_layers_enabled",
            "flags.character_speech_enabled", "flags.style_scope_enabled",
            "flags.postprocess_form_guard_enabled"},
        "flags_character": {
            "flags.self_model_enabled", "flags.trait_rules_enabled",
            "flags.legacy_traits_migration_enabled",
            "flags.character_layers_enabled",
            "flags.character_speech_enabled", "flags.style_scope_enabled",
            "flags.postprocess_form_guard_enabled"},
    }
    for gid, owner_keys in allowed.items():
        members = [s for s in pc.REGISTRY.values() if s.group == gid]
        assert members, f"{gid}: пустая группа"
        keys = {s.pg_key for s in members}
        assert keys == owner_keys, f"{gid}: orphan controls: {keys ^ owner_keys}"


def test_m3_effective_state_scenarios(hot_with, monkeypatch):
    """Own effective state §4.3: defaults → both; product OFF →
    product_toggle; env OFF → emergency_env (env важнее UI)."""
    set_config_cache(None)
    for module_id in ("stories", "character", "experience"):
        assert mr.effective_gate(module_id) == (True, True, "both")
    # random: мастера-тумблера нет → requested константен, ось одна — env
    assert mr.effective_gate("random") == (True, True, "both")

    hot_with({"flags.stories_vitrina_enabled": False,
              "flags.self_model_enabled": False,
              "memory.experience_learning_enabled": False})
    assert mr.effective_gate("stories")[1:] == (False, "product_toggle")
    assert mr.effective_gate("character")[1:] == (False, "product_toggle")
    assert mr.effective_gate("experience")[1:] == (False, "product_toggle")

    set_config_cache(None)
    monkeypatch.setattr(type(settings), "MCA_STORIES_VITRINA_ENABLED", False)
    monkeypatch.setattr(type(settings), "MCA_SELF_MODEL_ENABLED", False)
    monkeypatch.setattr(type(settings), "MCA_EXPERIENCE_LESSONS_ENABLED",
                        False)
    monkeypatch.setattr(type(settings), "MCA_RANDOM_SOURCE_ENABLED", False)
    for module_id in F4_MODULE_IDS:
        requested, effective, source = mr.effective_gate(module_id)
        assert (requested, effective, source) == (True, False, "emergency_env")


def test_m3_runtime_gates_follow_product_toggle(hot_with):
    """M1-семантика §3.3 на новых подмодулях: product OFF душит runtime-гейт
    (hot, без рестарта); env OFF — тоже (бит-паритет baseline)."""
    hot_with({"flags.stories_vitrina_enabled": False,
              "flags.episodes_backfill_enabled": False,
              "flags.trait_rules_enabled": False})
    assert mca_gates.stories_vitrina_enabled() is False
    assert mca_gates.episodes_backfill_enabled() is False
    assert mca_gates.trait_rules_enabled() is False
    # соседи по группе не затронуты
    assert mca_gates.stories_manage_enabled() is True
    assert mca_gates.episodes_enabled() is True
    assert mca_gates.self_model_enabled() is True


def test_m3_submaster_inertia_preserved(hot_with):
    """Композит mca-05 сохранён: подгейты эпизодов инертны при мастере OFF
    (любой из осей)."""
    hot_with({"flags.episodes_enabled": False})
    assert mca_gates.episodes_enabled() is False
    assert mca_gates.episodes_backfill_enabled() is False
    assert mca_gates.episodes_continuation_enabled() is False
    assert mca_gates.episodes_compiler_facade_enabled() is False


def test_m3_registry_gate_payload_for_frontend():
    """registry_for_frontend несёт config_tab + честный gate-снимок
    (requested/effective/source) — носитель /api/config не менялся."""
    data = {e["id"]: e for e in mr.registry_for_frontend()}
    for module_id in F4_MODULE_IDS:
        entry = data[module_id]
        assert entry["parent_id"] == F4_PARENTS[module_id]
        assert entry["config_tab"] == F4_CONFIG_TABS[module_id]
        gate = entry["gate"]
        assert gate["requested"] is True and gate["effective"] is True
        assert gate["source"] == "both"
        assert gate["env_param"]
    assert data["random"]["master_param"] == ""
    assert "no master" in data["random"]["rationale"].lower()


# ═══ M4 — drift (новая спецификация без обязательных полей → RED) ═══════════

def test_m4_all_registered_specs_validate():
    for spec in mr.MODULE_REGISTRY.values():
        assert mr.validate_spec(spec) == [], (
            f"{spec.id}: {mr.validate_spec(spec)}")


def test_m4_broken_product_module_is_red():
    from services.module_registry import ModuleSpec
    base = dict(
        id="broken", title="X", parent_id=None, description="x",
        runtime_gate="global", settings_groups=(), status_source="s",
        help_anchor="h")

    def spec_with(**kw):
        params = dict(base)
        params.update(kw)
        return ModuleSpec(**params)

    # product_module без master_param → RED
    errs = mr.validate_spec(spec_with(master_param=""))
    assert any("product_module без master_param" in e for e in errs)
    # выдуманный master_param → RED
    errs = mr.validate_spec(spec_with(master_param="flags.nonexistent",
                                      classification="submodule",
                                      rationale="r"))
    assert any("вне каталога" in e for e in errs)
    # «no master» без rationale → RED
    errs = mr.validate_spec(spec_with(master_param="",
                                      classification="submodule",
                                      rationale="r"))
    assert any("no master" in e for e in errs)
    # «no master» с явным rationale (подобно random) → OK
    ok = mr.validate_spec(spec_with(master_param="",
                                    classification="submodule",
                                    rationale="shared subsystem; no master: "
                                              "мастер — env-ось"))
    assert ok == []
    # группа вне GROUPS → RED
    errs = mr.validate_spec(spec_with(master_param="",
                                      classification="submodule",
                                      settings_groups=("nope_group",),
                                      rationale="no master: x"))
    assert any("вне GROUPS" in e for e in errs)
    # неизвестная classification/visibility → RED
    errs = mr.validate_spec(spec_with(master_param="",
                                      classification="wat",
                                      rationale="no master: x"))
    assert any("classification" in e for e in errs)


# ═══ Фронт: подкарточки рендерятся из реестра (f3ApplyModuleRegistry) ═══════

def test_js_submodule_cards_via_registry():
    js = APP_JS.read_text(encoding="utf-8")
    # F4-ветка подмодулей в merge-механике F3 (каркас не сломан)
    assert "f3ApplyModuleRegistry" in js
    assert "submoduleOf: spec.parent_id" in js
    assert "settingsGroups: Array.isArray(spec.settings_groups)" in js
    assert "F4_ICONS" in js
    # «только свои ключи»: фильтр групп у подмодулей
    assert "allow.indexOf(g.id) < 0" in js
    # честный гейт подмодуля на «Обзоре»
    assert "f4ModuleGate" in js
    assert "f4RelatedLinks" in js
    # ссылки из Initiative → owner-карточка «Случайность»
    assert "#/modules/random" in js


def test_js_hardcoded_modules_not_duplicated():
    """Новые подмодули приходят ИЗ РЕЕСТРА: в fallback-витрине MODULES
    дублирующих карточек нет (kanon = registry, §3.1)."""
    js = APP_JS.read_text(encoding="utf-8")
    for card in ("mod_stories", "mod_character", "mod_experience",
                 "mod_random"):
        assert f"id: '{card}'" not in js, f"{card} задублирован в витрине"


def test_html_overview_gate_block():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "data-f4-module-gate" in html
    assert "data-initiative-status" in html  # F3-блок не тронут
