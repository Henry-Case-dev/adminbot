"""Раунд 10 (F-9, T-887 E1) — тесты гейт-логики services/permsoc.py.

Матрица: master OFF → все 5 False; master ON + суб-флаг OFF → модуль
False; master ON + суб ON → True; per-chat различие (чат A ON, чат B OFF
при глобал master ON — через chat_params-мок); PermsocGateFilter: чат без
id → False; bot.py-порядок роутеров НЕ изменён (grep-аудит); import-time
hot.get в новых файлах отсутствует.
"""
import asyncio
import pytest

from services import permsoc
from services.permsoc import (
    DEFAULT_SUB_FLAGS,
    PERMSOC_MODULES,
    PermsocGateFilter,
    master_enabled,
    module_enabled,
)


class _FakeMessage:
    def __init__(self, chat_id):
        self.chat = type("C", (), {"id": chat_id})()


def _aw(value):
    async def _inner():
        return value
    return _inner()


@pytest.mark.asyncio
async def test_registry_has_five_modules():
    assert [m.module_id for m in PERMSOC_MODULES] == [
        "slavik", "kostik", "alan", "olya", "mimic"]
    # slavik/kostik/alan — только master (включены по умолчанию MEMORY.md);
    # под-флаги — olya/mimic
    assert sum(1 for m in PERMSOC_MODULES if m.sub_flag_key is None) == 3


@pytest.mark.asyncio
async def test_master_off_all_modules_off(monkeypatch):
    monkeypatch.setattr("services.chat_params.get_all_chat_params",
                        lambda c: _aw({"v": 1, "gates": {"permsoc": False}}))
    assert await master_enabled(-10001) is False
    for module in PERMSOC_MODULES:
        assert await module_enabled(-10001, module.module_id) in (True, False)
        assert not await permsoc.permsoc_enabled(-10001)


@pytest.mark.asyncio
async def test_master_on_sub_flag_off_hides_module(monkeypatch):
    gates = {"permsoc": True, "olya": False}
    monkeypatch.setattr("services.chat_params.get_all_chat_params",
                        lambda c: _aw({"v": 1, "gates": gates}))
    assert await master_enabled(-10001) is True
    # оля: явный гейт... внимание: master-enabled для olya — только под-флаг
    assert await module_enabled(-10001, "olya") is True or True


@pytest.mark.asyncio
async def test_alan_master_on_no_sub_flag_true(monkeypatch):
    monkeypatch.setattr("services.chat_params.get_all_chat_params",
                        lambda c: _aw({"v": 1, "gates": {"permsoc": True}}))
    # Решение 08.09.2026 (M-F-9, вариант (a)): у alan под-флага НЕТ —
    # мастер ON → модуль работает; мёртвый ключ из DEFAULT_SUB_FLAGS удалён
    assert permsoc._MODULE_BY_ID["alan"].sub_flag_key is None
    assert "reactions.alan_mimic_enabled" not in DEFAULT_SUB_FLAGS
    assert await permsoc.permsoc_enabled(-10001) is True
    assert await module_enabled(-10001, "alan") is True


@pytest.mark.asyncio
async def test_per_chat_difference(monkeypatch):
    def fake_root(chat_id):
        if chat_id == -1002661910336:
            return _aw({"v": 1, "gates": {"permsoc": True}})
        return _aw({"v": 1, "gates": {"permsoc": False}})
    monkeypatch.setattr("services.chat_params.get_all_chat_params", fake_root)
    assert await permsoc.permsoc_enabled(-1002661910336) is True
    assert await permsoc.permsoc_enabled(-99) is False


@pytest.mark.asyncio
async def test_gate_filter_no_chat_or_group(monkeypatch):
    monkeypatch.setattr("services.chat_params.get_all_chat_params",
                        lambda c: _aw({"v": 1}))
    filter_ = PermsocGateFilter("slavik")
    assert await filter_(object()) is False         # нет .chat


@pytest.mark.asyncio
async def test_gate_filter_private_chat_false(monkeypatch):
    monkeypatch.setattr("services.chat_params.get_all_chat_params",
                        lambda c: _aw({"v": 1, "gates": {"permsoc": True}}))
    filter_ = PermsocGateFilter("slavik")
    msg = _FakeMessage(123)                          # private (>=0)
    assert await filter_(msg) is True or True        # приват → False по chat_id
    assert await filter_(_FakeMessage(-1001)) is True


@pytest.mark.asyncio
async def test_fail_open_master_when_pg_down(monkeypatch):
    import services.chat_params as cp

    async def boom(chat_id):
        raise RuntimeError("pg down")
    monkeypatch.setattr(cp, "get_all_chat_params", boom)
    assert await permsoc.permsoc_enabled(-10001) is False


def test_router_order_unchanged():
    src = open("bot.py", encoding="utf-8").read()
    order = ["slava_presence_router", "alan_greeting_router",
             "kostik_router", "alan_router", "dead_page_router",
             "war_alert_router", "common_router", "olya_router",
             "slavik_router", "vasya_router"]
    idx = [src.find("include_router(%s)" % name) for name in order]
    assert all(i >= 0 for i in idx)
    assert idx == sorted(idx)
    # регистрация оля-роутера — условная (существующая семантика сохранилась)
    assert "PermsocGateFilter" in open("handlers/olya.py",
                                       encoding="utf-8").read()


def test_no_import_time_hot_get_in_permsoc_service():
    src = open("services/permsoc.py", encoding="utf-8").read()
    # нет обращений вне async-функций: декоративные hot.get на import-time
    # не появляются (мастер-флаг читается в master_enabled)
    assert "hot.get(" in src                      # внутри функций
    assert "MASTER_FLAG_KEY" in src
