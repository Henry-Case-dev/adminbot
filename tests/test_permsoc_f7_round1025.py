"""F7 (10.25, ADR-1025-20 D3/D6) — серверные per-chat блок-гейты PERMsoc.

Проверяется РЕАЛЬНОЕ поведение (не только grep-маркеры):
  * `feature_gates`: `permsoc_reactions`/`permsoc_schedule` ∈ ALL_GATED_FEATURES,
    default ON (baseline), явный chat-гейт побеждает;
  * `permsoc.block_enabled` — блок-гейт + kill-switch `PERMSOC_BLOCK_GATES_ENABLED`
    (OFF → baseline True), fail-open OFF при исключении;
  * `PermsocBlockGate` — BaseFilter (нет чата → False);
  * goodmorning `_tick` — «фоновая задача прекращается» для OFF-чата;
  * RBAC: `permsoc*` → who_can_toggle='global' / PUT только global admin;
  * хендлеры war/common/vasya/slavik/alan несут добавочный фильтр.
"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import settings
from services import feature_gates, permsoc
from services.goodmorning_scheduler import GoodmorningSchedulerService
from services.permsoc import PermsocBlockGate

ROOT = Path(__file__).resolve().parent.parent
GATES_API = (ROOT / "web" / "api" / "gates.py").read_text(encoding="utf-8")


def _aw(value):
    async def _inner():
        return value
    return _inner()


class _FakeMessage:
    def __init__(self, chat_id):
        self.chat = type("C", (), {"id": chat_id})()


# ── feature_gates: новые фичи ──────────────────────────────────────────────

def test_new_block_features_registered():
    assert "permsoc_reactions" in feature_gates.ALL_GATED_FEATURES
    assert "permsoc_schedule" in feature_gates.ALL_GATED_FEATURES
    # default ON — baseline (нет явного гейта → функция работает).
    assert feature_gates.DEFAULT_BY_FEATURE["permsoc_reactions"] is True
    assert feature_gates.DEFAULT_BY_FEATURE["permsoc_schedule"] is True
    # НЕ тяжёлые → auto_opt_in не срабатывает.
    assert "permsoc_reactions" not in feature_gates.HEAVY_FEATURES
    assert "permsoc_schedule" not in feature_gates.HEAVY_FEATURES


@pytest.mark.asyncio
async def test_gates_enabled_new_features(monkeypatch):
    monkeypatch.setattr("services.hot_config.get",
                        lambda key, default=None: default)
    # нет явного гейта → default ON
    assert await feature_gates.gates_enabled(
        -100, "permsoc_schedule", root={"v": 1}) is True
    # явный chat-гейт OFF побеждает
    assert await feature_gates.gates_enabled(
        -100, "permsoc_schedule",
        root={"v": 1, "gates": {"permsoc_schedule": False}}) is False


# ── permsoc.block_enabled ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_block_enabled_reads_gate(monkeypatch):
    def fake_root(chat_id):
        if chat_id == -1:
            return _aw({"v": 1, "gates": {"permsoc_schedule": False}})
        return _aw({"v": 1, "gates": {}})
    monkeypatch.setattr("services.chat_params.get_all_chat_params", fake_root)
    assert await permsoc.block_enabled(-1, "schedule") is False
    assert await permsoc.block_enabled(-2, "schedule") is True   # baseline ON


@pytest.mark.asyncio
async def test_block_enabled_killswitch_off_baseline(monkeypatch):
    monkeypatch.setattr(type(settings), "PERMSOC_BLOCK_GATES_ENABLED", False)
    monkeypatch.setattr("services.chat_params.get_all_chat_params",
                        lambda c: _aw({"v": 1,
                                       "gates": {"permsoc_schedule": False}}))
    # OFF kill-switch → новые гейты не влияют (baseline True).
    assert await permsoc.block_enabled(-1, "schedule") is True
    assert await permsoc.block_enabled(-1, "reactions") is True


@pytest.mark.asyncio
async def test_block_enabled_fail_open_off(monkeypatch):
    def boom(chat_id):
        raise RuntimeError("pg down")
    # gates_enabled сам fail-open, но прямой сбой проброса → False.
    monkeypatch.setattr("services.feature_gates.gates_enabled",
                        AsyncMock(side_effect=RuntimeError("pg down")))
    assert await permsoc.block_enabled(-1, "reactions") is False


@pytest.mark.asyncio
async def test_block_gate_filter_no_chat(monkeypatch):
    monkeypatch.setattr("services.chat_params.get_all_chat_params",
                        lambda c: _aw({"v": 1}))
    filt = PermsocBlockGate("reactions")
    assert await filt(object()) is False          # нет .chat
    assert await filt(_FakeMessage(-1001)) is True  # baseline ON


# ── goodmorning: фон прекращается для OFF-чата ──────────────────────────────

@pytest.mark.asyncio
async def test_goodmorning_tick_skips_disabled_chat(monkeypatch):
    relay = MagicMock()
    relay.send_goodmorning = AsyncMock(return_value=True)
    service = GoodmorningSchedulerService(
        relay=relay, time_str="07:00", tz="Asia/Yekaterinburg",
        target_chat_ids=(1, 2))

    async def fake_block(chat_id, block_id):
        return chat_id != 1          # чат 1 выключен
    monkeypatch.setattr("services.permsoc.block_enabled", fake_block)

    await service._tick()
    assert relay.send_goodmorning.await_count == 1
    relay.send_goodmorning.assert_any_await(2)
    assert relay.send_goodmorning.await_args_list == [((2,), {})] or \
        relay.send_goodmorning.await_args_list[0][0] == (2,)


@pytest.mark.asyncio
async def test_goodmorning_tick_baseline_all_sent(monkeypatch):
    relay = MagicMock()
    relay.send_goodmorning = AsyncMock(return_value=True)
    service = GoodmorningSchedulerService(
        relay=relay, time_str="07:00", tz="Asia/Yekaterinburg",
        target_chat_ids=(1, 2, 3))

    async def fake_block(chat_id, block_id):
        return True
    monkeypatch.setattr("services.permsoc.block_enabled", fake_block)

    await service._tick()
    assert relay.send_goodmorning.await_count == 3


# ── RBAC: permsoc* — global ────────────────────────────────────────────────

def test_who_can_toggle_permsoc_family_global():
    # атомарный маркер: всё семейство permsoc* → 'global'.
    assert 'who[f] = "global" if f.startswith("permsoc")' in GATES_API
    assert 'payload.feature.startswith("permsoc")' in GATES_API


# ── Хендлеры: добавочный фильтр ────────────────────────────────────────────

@pytest.mark.parametrize("rel,snippet", [
    ("handlers/war_alert.py", 'PermsocBlockGate("reactions")'),
    ("handlers/common.py", 'PermsocBlockGate("reactions")'),
    ("handlers/vasya.py", 'PermsocBlockGate("reactions")'),
    ("handlers/slavik.py", 'PermsocBlockGate("reactions")'),
    ("handlers/alan.py", 'PermsocBlockGate("reactions")'),
    ("handlers/alan_greeting.py", 'PermsocBlockGate("reactions")'),
])
def test_handlers_have_block_gate(rel, snippet):
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert snippet in src, rel


def test_handlers_master_filters_kept():
    """Существующие PermsocGateFilter не тронуты (master остаётся у alan/
    slavik/mimic)."""
    for rel in ("handlers/alan.py", "handlers/alan_greeting.py",
                "handlers/slavik.py", "handlers/common.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "PermsocGateFilter(" in src, rel


# ── H-F7-7 (fix): тип списков ID Оли — серверное сравнение ─────────────────
# Регрессия M-F7-2: `list-editor` коэрцировал ID в строки, а сервер сравнивает
# `origin.chat.id`/`sender_user.id` (int) через `in list` → строки не
# находились. Здесь — эмуляция реального пути фильтра: числа совпадают,
# строки (старое поведение) — нет.

@pytest.mark.asyncio
@pytest.mark.parametrize("stored,matched", [
    ([-100123, 523131145], True),          # после фикса: числа
    (["-100123", "523131145"], False),     # строка-регрессия: мимо
])
async def test_olya_saveasbot_list_type_comparison(make_message, stored, matched):
    from dataclasses import replace

    from aiogram.enums import ContentType
    from aiogram.types import MessageOriginChannel

    import filters.olya_video as filter_mod
    from filters.olya_video import OlyaVideoFilter

    origin = MagicMock(spec=MessageOriginChannel)
    origin.chat = MagicMock()
    origin.chat.id = -100123

    def hot_get(key, default=None):
        if key == "reactions.olya_saveasbot_channel_ids":
            return stored
        return default

    mod = replace(settings, OLYA_ALWAYS_SEND=False, OLYA_REPOST_ENABLED=True,
                  OLYA_CAPTION_ENABLED=False)
    with patch.object(filter_mod, "settings", mod), \
            patch.object(filter_mod.hot, "get", hot_get):
        f = OlyaVideoFilter()
        msg = make_message(from_id=settings.OLYA_USER_ID, text=None,
                           content_type=ContentType.VIDEO, forward_origin=origin)
        result = await f(msg)

    if matched:
        assert isinstance(result, dict) and result["is_saveasbot"] is True
    else:
        assert result is False
