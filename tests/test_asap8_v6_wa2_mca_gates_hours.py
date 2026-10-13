"""ASAP 8 v6 Wave A2 — D09-хвост: `or 7` в гейте расписания Deep Sleep.

Root cause (ledger D09/18F.2; incidental finding W-A1): `_schedule_gate`
(mca_gates) читал `memory.deep_sleep_hour` через `int(x or 7)` — ВАЛИДНЫЙ 0
(00:00) подменялся целью 07:00. После фикса воркера (`_deep_tick` →
`_hour_or`, W-A1) гейт и исполнитель расходились: воркер запускал Deep Sleep
в полночь, а гейт/трасса считали час чужим (и наоборот при чтении трассы).

Контракт: None/missing/пусто/мусор → env-дефолт DEEP_SLEEP_HOUR;
числовой 0 (и "0") → 0; 01:00 → 1; 23:00 → 23; detail-трасса называет
реальную цель. Fail-open при ошибке резолва сохранён.

TEST-LIFECYCLE: REGRESSION owner=ASAP8-v6/D09
"""
import pytest

from config.settings import settings
from services import mca_gates
import services.dream_worker as dw
import services.worker_settings as worker_settings

CHAT_ID = -100300


def _patch_gate(monkeypatch, *, hour: int, hour_value, trigger_value="fixed"):
    """Подмена per-chat резолва hot-ключей и local-часа."""

    async def fake_resolve(key, *, chat_id=None, default=None):
        if key == "memory.deep_sleep_hour":
            return hour_value
        if key == "memory.deep_sleep_trigger":
            return trigger_value
        return default

    monkeypatch.setattr(worker_settings, "resolve_setting_cached", fake_resolve)
    monkeypatch.setattr(dw, "_local_hour", lambda now, tz=None: hour)


# ── 00:00 — регрессия root cause ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_open_at_midnight_when_configured_00(monkeypatch):
    """00:00 настроен, local-час 00:00 → гейт ОТКРЫТ (раньше `or 7` считал
    цель 7 и полночь блокировалась как «вне окна»)."""
    _patch_gate(monkeypatch, hour=0, hour_value=0)
    assert await mca_gates._schedule_gate(CHAT_ID, 0, None) is None


@pytest.mark.asyncio
async def test_gate_blocks_at_07_for_midnight_config(monkeypatch):
    """Регрессия root cause: цель 00:00 при часе 07:00 → блок; при этом
    detail-трасса называет РЕАЛЬНУЮ цель 0, а не подменённую 7."""
    _patch_gate(monkeypatch, hour=7, hour_value=0)
    st = await mca_gates._schedule_gate(CHAT_ID, 0, None)
    assert st is not None and st.blocked is True
    assert st.reason == "schedule_outside_window"
    assert "memory.deep_sleep_hour=0" in (st.detail or ""), st.detail
    assert "now_hour=7" in (st.detail or ""), st.detail


@pytest.mark.asyncio
async def test_gate_string_zero_from_chat_params(monkeypatch):
    """Значение "0" строкой (формат chat_params) — тоже валидная полночь."""
    _patch_gate(monkeypatch, hour=0, hour_value="0")
    assert await mca_gates._schedule_gate(CHAT_ID, 0, None) is None


# ── 01:00 / 23:00 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_regular_hours_01_and_23(monkeypatch):
    for cfg_hour, tick_hour in ((1, 1), (23, 23)):
        _patch_gate(monkeypatch, hour=tick_hour, hour_value=cfg_hour)
        assert await mca_gates._schedule_gate(CHAT_ID, 0, None) is None, cfg_hour
        # чужой час → блок с верной целью в трассе
        _patch_gate(monkeypatch, hour=(tick_hour + 1) % 24, hour_value=cfg_hour)
        st = await mca_gates._schedule_gate(CHAT_ID, 0, None)
        assert st is not None and st.blocked, cfg_hour
        assert f"memory.deep_sleep_hour={cfg_hour}" in (st.detail or "")


# ── missing / мусор → env-дефолт ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_missing_value_uses_env_default(monkeypatch):
    """None/missing → env-дефолт DEEP_SLEEP_HOUR (не литерал 7, который
    может быть легально переопределён владельцем env)."""
    _patch_gate(monkeypatch, hour=settings.DEEP_SLEEP_HOUR, hour_value=None)
    assert await mca_gates._schedule_gate(CHAT_ID, 0, None) is None
    _patch_gate(monkeypatch, hour=0, hour_value=None)
    st = await mca_gates._schedule_gate(CHAT_ID, 0, None)
    assert st is not None and st.blocked
    assert f"memory.deep_sleep_hour={settings.DEEP_SLEEP_HOUR}" in (st.detail or "")


@pytest.mark.asyncio
async def test_gate_garbage_value_uses_env_default(monkeypatch):
    _patch_gate(monkeypatch, hour=settings.DEEP_SLEEP_HOUR,
                hour_value="не-час")
    assert await mca_gates._schedule_gate(CHAT_ID, 0, None) is None


# ── Прежняя семантика гейта не тронута ───────────────────────────────────────

@pytest.mark.asyncio
async def test_trigger_not_fixed_skips_hour_check(monkeypatch):
    """trigger != 'fixed' → час вообще не проверяется (прочная ветка)."""
    _patch_gate(monkeypatch, hour=0, hour_value=0, trigger_value="after_sleep")
    assert await mca_gates._schedule_gate(CHAT_ID, 0, None) is None


@pytest.mark.asyncio
async def test_resolve_failure_still_fail_open(monkeypatch):
    """Ошибка резолва → None (fail-open), как и до фикса."""

    async def boom(key, *, chat_id=None, default=None):
        raise RuntimeError("pg down")

    monkeypatch.setattr(worker_settings, "resolve_setting_cached", boom)
    assert await mca_gates._schedule_gate(CHAT_ID, 0, None) is None


@pytest.mark.asyncio
async def test_env_defaults_unchanged():
    """Базлайн env-констант не сдвинут (менялась только семантика нуля)."""
    assert settings.DEEP_SLEEP_HOUR == 7
    assert settings.DEEP_SLEEP_TRIGGER == "after_sleep"
