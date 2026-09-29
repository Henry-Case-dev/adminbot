"""ASAP-3 T-4007 — unit-тесты model-aware capacity (ADR-1028-2 D1/D2).

Покрывает §37 TEST 4/TEST 5 на уровне формулы:
  * рост external → available ↓ (TEST 4);
  * рост окна → Unlimited ↑ без правки констант (TEST 5);
  * safety-множитель применяется РОВНО ОДИН раз (§4, §52.B);
  * window_source ∈ {model_map, env_override, unknown_fallback};
  * fallback-модель → min(primary, fallback);
  * policy: -1/0/None/>0 (D2), fail-open.
"""
import pytest

from config.settings import settings
from services import model_capacity as mc


@pytest.fixture(autouse=True)
def _clean_cache():
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    yield
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()


class TestResolveWindow:
    def test_known_model_map_source(self):
        window, source = mc.resolve_model_context_window("deepseek-chat")
        assert window == 131072
        assert source == mc.WINDOW_SOURCE_MAP

    def test_prefix_match_case_insensitive(self):
        window, source = mc.resolve_model_context_window("DeepSeek-R1-Distill-32B")
        assert window == 131072
        assert source == mc.WINDOW_SOURCE_MAP

    def test_unknown_model_fallback_16384(self):
        window, source = mc.resolve_model_context_window(
            "totally-unknown-model-xyz")
        assert window == 16384
        assert source == mc.WINDOW_SOURCE_FALLBACK

    def test_unknown_warns_once_per_model(self, caplog):
        mc.resolve_model_context_window("mystery-model")
        mc.resolve_model_context_window("mystery-model")
        mc.resolve_model_context_window("mystery-model")
        warnings = [r for r in caplog.records
                    if "unknown model" in r.getMessage()]
        assert len(warnings) == 1

    def test_env_override_priority_above_map(self, monkeypatch):
        # ClassVar патчится на КЛАССЕ instance, который реально читает модуль
        # (полный прогон содержит reload(config.settings) — класс сдвигается;
        # сервисы держат старый instance, поэтому целимся в type(mc.settings)).
        monkeypatch.setattr(type(mc.settings), "CHAT_MODEL_CONTEXT_WINDOW",
                            7777)
        window, source = mc.resolve_model_context_window("deepseek-chat")
        assert window == 7777
        assert source == mc.WINDOW_SOURCE_ENV
        # override действует и для неизвестной модели.
        window2, source2 = mc.resolve_model_context_window("no-such-model-2")
        assert (window2, source2) == (7777, mc.WINDOW_SOURCE_ENV)

    def test_empty_model_name_fallback(self):
        window, source = mc.resolve_model_context_window(None)
        assert window == 16384
        assert source == mc.WINDOW_SOURCE_FALLBACK

    def test_fallback_model_takes_min(self):
        window, source = mc.resolve_effective_window(
            "gpt-4o", "deepseek-chat")
        # primary 128000, fallback 131072 → min = 128000 (primary).
        assert window == 128000
        assert source == mc.WINDOW_SOURCE_MAP
        window2, _ = mc.resolve_effective_window(
            "deepseek-chat", "gpt-4")
        # fallback-окно (8192) меньше primary → conservative min.
        assert window2 == 8192

    def test_fallback_model_ignored_when_absent(self):
        window, _ = mc.resolve_effective_window("deepseek-chat", None)
        assert window == 131072


class TestBudgetFormula:
    def test_single_safety_multiplier(self):
        # window=115000, external=0, ratio=0 → base=115000;
        # reserve floor 1024 → base = 115000-1024 = 113976; /1.15 один раз.
        available, reserve = mc.compute_available_budget(115000, 0, 0.0)
        assert reserve == mc.OUTPUT_RESERVE_FLOOR
        assert available == int(113976 / 1.15)
        # Повторное деление НЕ происходит: 27826 ≈ 32000/1.15 один раз.
        available2, _ = mc.compute_available_budget(32000, 0, 0.0)
        assert available2 == int(30976 / 1.15)

    def test_output_reserve_floor_and_ratio(self):
        # ratio 0.10 от 100000 = 10000 > floor.
        _, reserve = mc.compute_available_budget(100000, 0, 0.10)
        assert reserve == 10000
        # Маленькое окно → floor 1024.
        _, reserve2 = mc.compute_available_budget(5000, 0, 0.10)
        assert reserve2 == 1024

    def test_growth_external_reduces_available(self):
        # §37 TEST 4: рост system/tools/personality → available ↓.
        small, _ = mc.compute_available_budget(131072, 4000, 0.10)
        big, _ = mc.compute_available_budget(131072, 12000, 0.10)
        assert big < small

    def test_growth_window_expands_unlimited(self):
        # §37 TEST 5: рост окна модели → Unlimited больше без правки констант.
        small, _ = mc.compute_available_budget(32768, 2000, 0.10)
        large, _ = mc.compute_available_budget(131072, 2000, 0.10)
        assert large > small

    def test_fail_open_zero_external(self):
        available, reserve = mc.compute_available_budget(131072, 0, 0.10)
        assert available >= 1 and reserve > 0

    def test_never_below_one(self):
        available, _ = mc.compute_available_budget(1100, 100000, 0.10)
        assert available == 1


class TestBudgetPolicy:
    def test_minus_one_is_unlimited_physical(self):
        budget, mode = mc.apply_budget_policy(25000, -1)
        assert budget == 25000
        assert mode == "unlimited"

    def test_zero_and_none_dynamic_default_16000(self):
        budget, mode = mc.apply_budget_policy(25000, 0)
        assert (budget, mode) == (16000, "dynamic")
        budget2, mode2 = mc.apply_budget_policy(25000, None)
        assert (budget2, mode2) == (16000, "dynamic")

    def test_dynamic_capped_by_available(self):
        budget, mode = mc.apply_budget_policy(9000, 0)
        assert (budget, mode) == (9000, "dynamic")

    def test_positive_is_explicit_cap(self):
        budget, mode = mc.apply_budget_policy(25000, 8000)
        assert (budget, mode) == (8000, "cap")
        budget2, mode2 = mc.apply_budget_policy(5000, 8000)
        # physical window остаётся верхней границей.
        assert (budget2, mode2) == (5000, "cap")

    def test_garbage_falls_back_dynamic(self):
        budget, mode = mc.apply_budget_policy(25000, "abc")
        assert (budget, mode) == (16000, "dynamic")
