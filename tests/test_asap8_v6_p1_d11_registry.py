"""ASAP 8 v6 P1 — D11: Module registry completeness (v6 §C D11, v5 §8/§17).

Инвентарь (M2-паттерн, расширенный на новые модули): каждый operator-facing
feature имеет ModuleSpec (master/effective/settings-группа) ЛИБО явную
infrastructure/maintenance-классификацию с rationale и ссылкой на настройки
в правильном родителе:
* Vision / Nostalgia / Сон / Factcheck — product_module (мастер + группы в
  каталоге, карточки витрины существуют — новых top-level карточек НЕТ);
* Temporal Factcheck — submodule «Фактчек» (мастер temporal.tool_enabled);
* Embeddings/GraphRAG control plane — infrastructure (no master, rationale +
  настройки в правильных родителях);
* Dossier rebuild — maintenance (rationale + operator-поверхность родителя).

Дополнительно: analytics_anchor каждого нового spec — реальный process_id
реестра процессов (провенанс телеметрии); ENV_GATES-ось принадлежит
MODULE_ENV_GATES; «100 карточек» не нарушено; F5-gate не регрессировал.

TEST-LIFECYCLE: CONTRACT owner=ASAP8-v6/D11
"""
import pytest

from config.settings import settings
from services import mca_gates
from services import module_registry as mr
from services import param_catalog as pc

D11_PRODUCT = ("vision", "nostalgia", "sleep", "factcheck")
D11_SUBMODULES = {"factcheck_temporal": "factcheck"}
D11_GROUP_TABS = {
    "factcheck": ("flags_module_factcheck", "limits_factcheck"),
    "factcheck_temporal": ("temporal_factcheck",),
    "vision": ("flags_module_vision", "limits_vision"),
    "nostalgia": ("memory_nostalgia",),
    "sleep": ("memory_dream",),
}


class TestD11Inventory:
    def test_product_modules_registered_with_catalog_master(self):
        for module_id in D11_PRODUCT:
            spec = mr.MODULE_REGISTRY[module_id]
            assert spec.classification == "product_module"
            assert spec.parent_id is None
            entry = pc.get_by_pg_key(spec.master_param)
            assert entry is not None, f"{module_id}: master вне каталога"
            assert entry.migratable
            assert mr.validate_spec(spec) == []
            # группы на своей поверхности (tab группы == tab карточки)
            for gid in D11_GROUP_TABS[module_id]:
                members = [s for s in pc.REGISTRY.values() if s.group == gid]
                assert members, f"{module_id}: пустая группа {gid}"

    def test_temporal_factcheck_submodule_of_factcheck(self):
        spec = mr.MODULE_REGISTRY["factcheck_temporal"]
        assert spec.classification == "submodule"
        assert spec.parent_id == "factcheck"
        # родитель существует (не fake parent, F5)
        assert spec.parent_id in mr.MODULE_REGISTRY
        assert spec.config_tab == "mod_factcheck"
        assert pc.group_tab("temporal_factcheck") == spec.config_tab
        assert mr.validate_spec(spec) == []

    def test_embeddings_control_plane_infrastructure_rationale(self):
        spec = mr.MODULE_REGISTRY["embeddings"]
        assert spec.classification == "infrastructure"
        # no master — сознательно; rationale называет настройки родителя
        assert spec.master_param == ""
        low = spec.rationale.lower()
        assert "no master" in low
        assert "models_embeddings" in spec.rationale
        assert "flags_memory" in spec.rationale      # graph-оси в «Памяти»
        assert mr.validate_spec(spec) == []

    def test_dossier_maintenance_rationale_points_at_parent_surface(self):
        """Dossier rebuild — maintenance: rationale обязан называть
        operator-поверхность родителя (не голое «infrastructure»)."""
        rationalized = " ".join(
            text for _cls, text, _names in mr.INFRASTRUCTURE_RATIONALE)
        assert "досье-модалка" in rationalized
        assert "MCA_DOSSIER_REBUILD_ENABLED" in rationalized or any(
            "MCA_DOSSIER_REBUILD_ENABLED" in names
            for _c, _t, names in mr.INFRASTRUCTURE_RATIONALE)

    def test_defaults_match_settings_canon(self):
        for key, expected in (
                ("flags.factcheck_enabled", settings.FACTCHECK_ENABLED),
                ("flags.vision_enabled", settings.VISION_ENABLED),
                ("memory.nostalgia_enabled", settings.NOSTALGIA_ENABLED),
                ("memory.dream_enabled", settings.DREAM_ENABLED),
                ("temporal.tool_enabled", settings.TEMPORAL_TOOL_ENABLED)):
            assert mr.PRODUCT_DEFAULTS[key] is expected, key

    def test_kill_switches_coverage_still_complete(self):
        owned: set[str] = set()
        for names in mr.MODULE_ENV_GATES.values():
            owned.update(names)
        rationalized: set[str] = set()
        for _c, _t, names in mr.INFRASTRUCTURE_RATIONALE:
            dup = (rationalized | owned) & set(names)
            assert not dup, f"дубль rationale/owner: {dup}"
            rationalized.update(names)
        assert set(mca_gates.KILL_SWITCHES) - owned - rationalized == set()
        assert (owned | rationalized) - set(mca_gates.KILL_SWITCHES) == set()

    def test_env_gates_axis_owned_by_module(self):
        for module_id, env_name in mr.ENV_GATES.items():
            assert module_id in mr.MODULE_REGISTRY
            assert env_name in mr.MODULE_ENV_GATES.get(module_id, ())

    def test_analytics_anchor_is_real_process(self):
        """D11.3 (телеметрия): analytics_anchor каждого spec — реальный
        process_id реестра процессов (labels привязаны к стадиям, не
        выдуманы)."""
        from services import mca_process_registry as pr
        process_ids = {getattr(d, "process_id", None)
                       for d in pr.PROCESS_REGISTRY}
        for module_id in D11_PRODUCT + tuple(D11_SUBMODULES) + \
                ("embeddings",):
            anchor = mr.MODULE_REGISTRY[module_id].analytics_anchor
            assert anchor in process_ids, \
                f"{module_id}: anchor {anchor!r} вне реестра процессов"

    def test_no_hundred_top_level_cards(self):
        """§4.2 «не делать 100 top-level карточек»: верхнеуровневых
        (parent None) записей — ограниченный закрытый набор."""
        top = [spec for spec in mr.MODULE_REGISTRY.values()
               if spec.parent_id is None
               and spec.classification == "product_module"]
        assert len(top) <= 12, f"top-level карточек стало {len(top)}"

    def test_registry_payload_for_new_modules(self):
        data = {e["id"]: e for e in mr.registry_for_frontend()}
        # B07 (v6.3): temporal — функция Фактчека, НЕ карточка модуля:
        # записи в MODULE_REGISTRY/inspector живут, в выдаче карточек её НЕТ.
        assert "factcheck_temporal" not in data
        assert "factcheck_temporal" in mr.MODULE_REGISTRY
        for module_id in D11_PRODUCT + ("embeddings",):
            entry = data[module_id]
            assert entry["gate"]["requested"] is not None
            assert entry["status_source"]
            assert entry["help_anchor"]
        # temporal-функция принадлежит поверхности Фактчека (родитель жив)
        assert mr.MODULE_REGISTRY["factcheck_temporal"].parent_id \
            in mr.MODULE_REGISTRY
        assert data["embeddings"]["classification"] == "infrastructure"


class TestD11EffectiveGates:
    def test_defaults_both_or_canon(self):
        from services.hot_config import set_config_cache
        set_config_cache(None)
        for module_id in D11_PRODUCT:
            requested, effective, source = mr.effective_gate(module_id)
            canon = mr.PRODUCT_DEFAULTS[mr.MODULE_REGISTRY[module_id]
                                        .master_param]
            assert requested is canon
            assert effective is canon
            assert source == ("both" if canon else "product_toggle")

    def test_product_toggle_off_stops_module(self, monkeypatch):
        from services.hot_config import set_config_cache

        class _FakeHot:
            def __init__(self, values):
                self._values = dict(values)

            def get(self, key, default=None):
                return self._values.get(key, default)

        set_config_cache(_FakeHot({"flags.vision_enabled": False,
                                   "temporal.tool_enabled": False}))
        try:
            assert mr.effective_gate("vision")[1:] == (False,
                                                       "product_toggle")
            assert mr.effective_gate(
                "factcheck_temporal")[1:] == (False, "product_toggle")
        finally:
            set_config_cache(None)

    def test_env_off_beats_product_toggle(self, monkeypatch):
        from services.hot_config import set_config_cache
        set_config_cache(None)
        monkeypatch.setattr(type(settings), "MCA_VISION_ENABLED", False)
        monkeypatch.setattr(type(settings),
                            "MCA_TEMPORAL_FACTCHECK_TOOL_ENABLED", False)
        assert mr.effective_gate("vision") == (False, False, "emergency_env")
        assert mr.effective_gate("factcheck_temporal") == (
            True, False, "emergency_env")


class TestF5NoRegression:
    def test_no_fake_parent_summary_gate(self):
        """F5 (§11/§28.10): fake parentGate снят — гейт каждого модуля
        считается ТОЛЬКО по его собственной product/env оси, никогда по
        родителю (§18H: «each feature checks its own effective gate»)."""
        for spec in mr.MODULE_REGISTRY.values():
            snap = mr.gate_snapshot(spec.id)
            assert snap["master_param"] == spec.master_param, spec.id
            assert snap["env_param"] == mr.ENV_GATES.get(spec.id, "")

    def test_new_submodule_parent_is_registered_module(self):
        """D11: новые submodules ссылаются родителем ТОЛЬКО на реальную
        запись реестра (не на «виртуальную» поверхность)."""
        for sub_id, parent in D11_SUBMODULES.items():
            assert parent in mr.MODULE_REGISTRY
            assert mr.MODULE_REGISTRY[sub_id].parent_id == parent

    def test_random_master_not_regressed(self):
        """F5 §5.3 (M7): Random master остаётся product-осью с тумблером."""
        spec = mr.MODULE_REGISTRY["random"]
        assert spec.master_param == "memory.random_enabled"
        assert mr.validate_spec(spec) == []
