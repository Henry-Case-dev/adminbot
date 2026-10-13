"""ASAP 8 v6 C06A — heartbeat observable (R1/R3 RCA `rca-c06a-initiative.md`).

Регрессия «Initiative ON часами, Status: не запускалось»:
  * R1: hot-ON мастера не запускал heartbeat до рестарта (джоба
    регистрировалась только в start() при уже-ON гейте) → теперь джоба
    регистрируется ВСЕГДА, гейт читается тиком (toggle симметричен);
  * R3: liveness-штамп тика был in-memory → рестарт врал «тик ещё не был»;
    теперь штамп персистентен (task_jobs, одна строка) и гидрируется при
    старте;
  * наблюдаемость: тик пишет INFO даже при пустом результате («tick ran,
    nothing due») — «мёртвый» и «праздный» различимы в журнале.

TEST-LIFECYCLE: REGRESSION owner=ASAP8-v6/C06A
"""
import json
import logging
import time

import pytest

from services import mca_gates
from services import mca_intents as mi
from services import mca_events
from services import memory_maintenance as mm
from services.database import DatabaseService
from services.memory_maintenance import MemoryMaintenanceService

CHAT = -100777


@pytest.fixture(autouse=True)
def _clean_mm_globals():
    """Module-globals memory_maintenance — изоляция между тестами."""
    mca_events.reset_pending()
    mm._heartbeat_last_tick.update({"ts": None, "due": 0, "enabled": None})
    saved_svc = mm._active_service
    mm._active_service = None
    yield
    mm._heartbeat_last_tick.update({"ts": None, "due": 0, "enabled": None})
    mm._active_service = saved_svc
    mca_events.reset_pending()


async def _db(tmp_path, name="c06a.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _mk_due(db, *, chat=CHAT, when=None):
    """Due-намерение (deferred с прошедшим next_check_at) — как в mca09."""
    svc = mi.get_service(db)
    intent_id, created = await svc.create_intent(
        chat, "follow_up", "unanswered_question",
        goal="Когда стрим?", reason="unanswered_question",
        source_refs=("msg:1",), topic_refs=("t:c06a",),
        created_at=int(time.time()) - 10)
    assert created
    assert await svc.defer(intent_id,
                           next_check_at=when or (int(time.time()) - 1),
                           activation_condition="time_due",
                           now=int(time.time()) - 10)
    return intent_id


async def _intent_status(db, intent_id):
    return await mi.get_service(db).store.get_intent(intent_id)


@pytest.mark.asyncio
async def test_hot_on_after_start_registers_job_and_ticks_without_restart(
        tmp_path, monkeypatch):
    """R1: master OFF при старте → джоба ВСЁ РАВНО зарегистрирована; hot-ON
    без рестарта → следующий тик работает (штамп обновлён, due найден)."""
    monkeypatch.setattr(mca_gates, "intents_enabled", lambda: False)
    db = await _db(tmp_path, "c06a_hoton.db")
    svc = MemoryMaintenanceService(db, memory=None, llm=None, bot=None)
    try:
        svc.start()
        job = svc._scheduler.get_job(
            MemoryMaintenanceService.JOB_INTENT_HEARTBEAT_ID)
        assert job is not None, ("v6 C06A R1: джоба heartbeat должна быть "
                                 "зарегистрирована независимо от гейта "
                                 "при старте")
        info = mm.intent_heartbeat_job_info()
        assert info["registered"] is True
        assert info["next_tick"] is not None

        # Хозяин включает тумблер (hot) — рестарта НЕТ, тот же сервис.
        monkeypatch.setattr(mca_gates, "intents_enabled", lambda: True)
        monkeypatch.setattr(mca_gates, "intent_heartbeat_enabled",
                            lambda: True)
        intent_id = await _mk_due(db)
        await svc._tick_intent_heartbeat()
        assert mm._heartbeat_last_tick["ts"] is not None
        assert mm._heartbeat_last_tick["enabled"] is True
        assert mm._heartbeat_last_tick["due"] >= 1
        # бот None → решение не принимается, но due-скан отработал честно:
        # deferred по сроку ре-активируется (контракт mca-09 «догон»),
        # намерение не потеряно
        row = await _intent_status(db, intent_id)
        assert row["status"] in ("pending", "deferred")
    finally:
        await svc.shutdown()
        await db.close()


@pytest.mark.asyncio
async def test_hot_off_stops_heartbeat_work(tmp_path, monkeypatch, caplog):
    """R1 (обратная сторона): hot-OFF останавливает работу тика — due не
    сканируется, штамп честно помечает enabled=False, INFO «tick ran» нет."""
    monkeypatch.setattr(mca_gates, "intents_enabled", lambda: True)
    monkeypatch.setattr(mca_gates, "intent_heartbeat_enabled", lambda: True)
    db = await _db(tmp_path, "c06a_off.db")
    intent_id = await _mk_due(db)
    svc = MemoryMaintenanceService(db, memory=None, llm=None, bot=None)
    try:
        svc.start()
        monkeypatch.setattr(mca_gates, "intents_enabled", lambda: False)
        with caplog.at_level(logging.INFO,
                             logger="services.memory_maintenance"):
            await svc._tick_intent_heartbeat()
        assert mm._heartbeat_last_tick["enabled"] is False
        msgs = [r.getMessage() for r in caplog.records
                if r.name == "services.memory_maintenance"]
        assert not any("tick ran" in m for m in msgs), \
            "инертный тик не должен писать INFO «tick ran»"
        row = await _intent_status(db, intent_id)
        assert row["status"] == "deferred"   # работа остановлена
    finally:
        await svc.shutdown()
        await db.close()


@pytest.mark.asyncio
async def test_restart_persists_last_tick_and_reregisters_job(
        tmp_path, monkeypatch):
    """R3: рестарт — durable-штамп гидрируется (последний тик переживает
    процесс), джоба перерегистрирована, registered доступен Status."""
    monkeypatch.setattr(mca_gates, "intents_enabled", lambda: True)
    monkeypatch.setattr(mca_gates, "intent_heartbeat_enabled", lambda: True)
    db = await _db(tmp_path, "c06a_restart.db")
    svc1 = MemoryMaintenanceService(db, memory=None, llm=None, bot=None)
    try:
        svc1.start()
        await svc1._tick_intent_heartbeat()
        ts_before = mm._heartbeat_last_tick["ts"]
        assert ts_before is not None
    finally:
        await svc1.shutdown()
    # durable-строка действительно записана
    cur = await db.db.execute(
        "SELECT heartbeat_at, payload FROM task_jobs WHERE job_id = ?",
        (mm._HEARTBEAT_LIVENESS_JOB_ID,))
    row = await cur.fetchone()
    assert row is not None and row["heartbeat_at"] == ts_before
    assert json.loads(row["payload"])["enabled"] is True

    # «Рестарт»: эмулируем новый процесс — in-memory штамп сброшен.
    mm._heartbeat_last_tick.update({"ts": None, "due": 0, "enabled": None})
    svc2 = MemoryMaintenanceService(db, memory=None, llm=None, bot=None)
    try:
        svc2.start()
        await svc2._hydrate_heartbeat_liveness()
        assert mm._heartbeat_last_tick["ts"] == ts_before
        assert mm._heartbeat_last_tick["enabled"] is True
        assert svc2._scheduler.get_job(
            MemoryMaintenanceService.JOB_INTENT_HEARTBEAT_ID) is not None
        info = mm.intent_heartbeat_job_info()
        assert info["registered"] is True
    finally:
        await svc2.shutdown()
        await db.close()


@pytest.mark.asyncio
async def test_empty_tick_logs_info_and_persists_stamp(
        tmp_path, monkeypatch, caplog):
    """Наблюдаемость: тик с пустым результатом пишет INFO («tick ran,
    nothing due») и пишет durable-штамп — «праздный» ≠ «мёртвый»."""
    monkeypatch.setattr(mca_gates, "intents_enabled", lambda: True)
    monkeypatch.setattr(mca_gates, "intent_heartbeat_enabled", lambda: True)
    db = await _db(tmp_path, "c06a_empty.db")
    svc = MemoryMaintenanceService(db, memory=None, llm=None, bot=None)
    try:
        svc.start()
        with caplog.at_level(logging.INFO,
                             logger="services.memory_maintenance"):
            await svc._tick_intent_heartbeat()
        msgs = [r.getMessage() for r in caplog.records
                if r.name == "services.memory_maintenance"]
        assert any("intent heartbeat tick ran" in m and "due=0" in m
                   for m in msgs), msgs
        cur = await db.db.execute(
            "SELECT heartbeat_at FROM task_jobs WHERE job_id = ?",
            (mm._HEARTBEAT_LIVENESS_JOB_ID,))
        row = await cur.fetchone()
        assert row is not None
        assert row["heartbeat_at"] == mm._heartbeat_last_tick["ts"]
    finally:
        await svc.shutdown()
        await db.close()
