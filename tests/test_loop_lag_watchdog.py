"""F-STALL-01: bounded loop-lag watchdog (наблюдаемость, не продукт).

Контракт модуля `services/loop_lag_watchdog`:

* (a) искусственная блокировка event loop ~2 s при пороге 0.3 s → ровно
  зафиксированное срабатывание с ненулевой длительностью и непустым снимком
  стеков всех потоков;
* (b) без блокировки за 2 s — 0 срабатываний (сторож при этом реально тикает);
* (c) антифлуд: одна блокировка 2 s при пороге 0.3 s даёт не более одной
  записи; повторная блокировка внутри окна подавляется;
* (d) невалидный/пустой env → заводской порог и рабочий старт; env-ноль —
  сторож не стартует.

Тесты используют настоящий `call_later`-механизм и настоящее логирование
(caplog), без подмены самого сторожа. RED на базе без модуля: ImportError.

TEST-LIFECYCLE: CONTRACT owner=F-STALL-01 / loop-lag observability
"""

import asyncio
import logging
import time

import pytest

from services import loop_lag_watchdog as llw

ENV_WARN = llw.ENV_WARN_S
ENV_INTERVAL = llw.ENV_MIN_INTERVAL_S


def _lag_records(caplog):
    return [r for r in caplog.records
            if getattr(r, "event", None) == "loop_lag"]


def _snapshot_of(record) -> str:
    message = record.getMessage()
    assert "snapshot_begin" in message and "snapshot_end" in message
    return message.split("snapshot_begin", 1)[1].split("snapshot_end", 1)[0]


# ── (a) блокировка цикла → одно срабатывание со стеком ─────────────────────


@pytest.mark.asyncio
async def test_blocked_loop_reports_nonzero_lag_and_thread_snapshot(caplog):
    caplog.set_level(logging.WARNING, logger=llw.__name__)
    watchdog = llw.LoopLagWatchdog(
        threshold_s=0.3, min_interval_s=60.0, tick_s=0.05)
    assert watchdog.start() is True, "сторож не стартовал в активном loop"
    try:
        await asyncio.sleep(0.15)   # базовые тики до блокировки
        time.sleep(2.0)             # синхронная блокировка event loop
        await asyncio.sleep(0.3)    # дать сработать просроченному таймеру
    finally:
        watchdog.stop()

    records = _lag_records(caplog)
    assert len(records) == 1, (
        f"ожидалось одно срабатывание на одну блокировку, получено "
        f"{len(records)} (ticks={watchdog.ticks})")
    record = records[0]
    assert record.levelno == logging.WARNING
    assert record.loop_lag_threshold_ms == 300
    assert record.loop_lag_ms > 0, "длительность лага не зафиксирована"
    assert record.loop_lag_ms >= 300, (
        f"зафиксирован лаг {record.loop_lag_ms} ms ниже порога")
    snapshot = _snapshot_of(record)
    assert record.loop_lag_snapshot_chars > 0
    assert "Thread" in snapshot, "снимок не содержит потоков"
    assert "File \"" in snapshot, "снимок не содержит кадров стека"
    # Ключевое для F-STALL-01: дамп снят ПОКА loop заблокирован, поэтому в
    # снимке остался сам блокирующий кадр (file:line), а не постыдный стек.
    assert "test_loop_lag_watchdog.py" in snapshot, (
        "в снимке нет кадра теста — дамп снят после разблокировки loop")
    assert "test_blocked_loop_reports_nonzero_lag_and_thread_snapshot" in (
        snapshot), "в снимке нет кадра заблокированного loop — виновник потерян"
    assert watchdog.triggers == 1
    assert watchdog.ticks >= 1


# ── (b) без блокировки — ноль срабатываний ─────────────────────────────────


@pytest.mark.asyncio
async def test_idle_loop_has_no_reports(caplog):
    caplog.set_level(logging.WARNING, logger=llw.__name__)
    watchdog = llw.LoopLagWatchdog(
        threshold_s=0.3, min_interval_s=60.0, tick_s=0.05)
    assert watchdog.start() is True
    try:
        await asyncio.sleep(2.0)
    finally:
        watchdog.stop()

    assert watchdog.ticks >= 20, (
        f"сторож почти не тикал ({watchdog.ticks}) — проверка недействительна")
    assert _lag_records(caplog) == []
    assert watchdog.triggers == 0
    assert watchdog.last_lag_s < 0.3


# ── (c) антифлуд: не более одной записи на серию блокировок ────────────────


@pytest.mark.asyncio
async def test_antiflood_one_record_per_blocked_episode(caplog):
    caplog.set_level(logging.WARNING, logger=llw.__name__)
    watchdog = llw.LoopLagWatchdog(
        threshold_s=0.3, min_interval_s=60.0, tick_s=0.05)
    assert watchdog.start() is True
    try:
        await asyncio.sleep(0.15)
        time.sleep(2.0)
        await asyncio.sleep(0.3)
        assert len(_lag_records(caplog)) == 1, (
            "одна блокировка должна давать ровно одну запись")
        # Вторая блокировка внутри окна антифлуда — подавлена.
        time.sleep(2.0)
        await asyncio.sleep(0.3)
    finally:
        watchdog.stop()

    assert len(_lag_records(caplog)) == 1, (
        "антифлуд не сработал: повторная блокировка добавила запись")
    assert watchdog.triggers == 1
    assert watchdog.suppressed >= 1, "подавленное срабатывание не учтено"


# ── (d) env: невалидное значение → заводной порог, старт не падает ─────────


@pytest.mark.asyncio
async def test_invalid_env_falls_back_to_factory_and_starts(
        monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger=llw.__name__)
    monkeypatch.setenv(ENV_WARN, "not-a-number")
    monkeypatch.setenv(ENV_INTERVAL, "abc")
    watchdog = llw.LoopLagWatchdog.from_env()
    assert watchdog.threshold_s == llw.DEFAULT_WARN_S == 5.0
    assert watchdog.min_interval_s == llw.DEFAULT_MIN_INTERVAL_S == 60.0
    assert watchdog.enabled is True
    assert watchdog.start() is True, "старт упал на невалидном env"
    try:
        await asyncio.sleep(0.1)
    finally:
        watchdog.stop()
    assert _lag_records(caplog) == []

    # Отрицательный порог — тоже невалиден, работает заводной дефолт.
    monkeypatch.setenv(ENV_WARN, "-3")
    assert llw.LoopLagWatchdog.from_env().threshold_s == llw.DEFAULT_WARN_S


@pytest.mark.asyncio
async def test_empty_env_uses_factory_threshold(monkeypatch):
    monkeypatch.delenv(ENV_WARN, raising=False)
    watchdog = llw.LoopLagWatchdog.from_env()
    assert watchdog.threshold_s == llw.DEFAULT_WARN_S
    assert watchdog.enabled is True


@pytest.mark.asyncio
async def test_env_zero_disables_watchdog(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger=llw.__name__)
    monkeypatch.setenv(ENV_WARN, "0")
    watchdog = llw.LoopLagWatchdog.from_env()
    assert watchdog.enabled is False
    assert watchdog.start() is False, "env-ноль должен выключать сторож"
    assert llw.start_from_env() is None
    await asyncio.sleep(0.1)
    assert _lag_records(caplog) == []


@pytest.mark.asyncio
async def test_no_running_loop_start_is_fail_open():
    """`start()` вне loop возвращает False, а не бросает (fail-open)."""
    watchdog = llw.LoopLagWatchdog(threshold_s=1.0)

    def _call() -> bool:
        return watchdog.start()

    assert await asyncio.to_thread(_call) is False
