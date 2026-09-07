"""Раунд 10 (F-10 T-893, фикс S3) — тесты scripts/backfill_feature_gates.py.

Проверки: патч-планировщик `build_gate_patch` (существующие гейты НЕ
затираются — идемпотентность), глобальные значения по цепочке
FLAG_KEYS/_global_flag_value (реальный ARR по фиксу S3: FLAG_BY_FEATURE
не существует), smoke функцию планирования без AttributeError.
"""
import pytest

from scripts.backfill_feature_gates import build_gate_patch
from services import feature_gates


def test_build_gate_patch_only_missing_features():
    """Запись — только отсутствующие гейты; существующие — no-op."""
    values = {"dream": True, "nostalgia": True, "lore_auto": True}
    patch = build_gate_patch({"dream": False}, values)
    assert patch == {"nostalgia": True, "lore_auto": True}
    # пустой root → все 3 тяжёлые
    patch2 = build_gate_patch({}, {"dream": True, "nostalgia": False,
                                   "lore_auto": True})
    assert patch2 == {"dream": True, "nostalgia": False, "lore_auto": True}


def test_build_gate_patch_idempotent():
    """Повторный запуск с уже записанными значениями → no-op (пустой)."""
    gates = {"dream": True, "nostalgia": True, "lore_auto": True}
    assert build_gate_patch(gates, gates) == {}
    assert build_gate_patch(None, {"dream": True}) == {"dream": True}


@pytest.mark.asyncio
async def test_global_flag_values_uses_flag_keys_chain(monkeypatch):
    """S3: глобальные значения резолвятся через FLAG_KEYS-цепочку
    (flags.<feature>_enabled → memory.<feature>_enabled → дефолт)."""
    import services.hot_config as hot
    fake = {
        "flags.dream_enabled": True,
        "flags.nostalgia_enabled": False,
        "flags.lore_auto_enabled": True,
    }
    monkeypatch.setattr(hot, "get", lambda key, default=None:
                        fake.get(key, default))
    values = await _global_flag_values_safe()
    assert values == {"dream": True, "nostalgia": False, "lore_auto": True}
    assert "permsoc" not in values           # backfill — только тяжёлые


async def _global_flag_values_safe():
    from scripts.backfill_feature_gates import global_flag_values
    return await global_flag_values()


def test_flag_keys_chain_covers_heavy():
    """Инвариант: для каждой тяжёлой фичи есть канонический ключ."""
    for feature in feature_gates.HEAVY_FEATURES:
        assert feature_gates.FLAG_KEYS[feature]
