"""Смоук раунда 10.16 (T-1647) — sleep «имитация реальной работы».

Реальный `DreamWorker` + SQLite in-memory, LLM замокан. Сценарии:
  * «тихий» режим (0 убеждений 3 дня) → fallback 2/Σ8 пропускает слабый кластер;
  * self-healing: после синтеза fallback выключается (база 3/Σ12);
  * fail-safe: ошибка БД на детекте → базовые пороги;
  * пре-гейт-лог `[Sleep]` виден в лог-ринге (WARNING).
"""
import asyncio
import logging
import time

import pytest

from services import hot_config as hot
from services.database import DatabaseService
from services.dream_worker import (
    DreamWorker,
    _FALLBACK_MIN_CLUSTER_SIZE,
    _FALLBACK_MIN_IMPORTANCE_SUM,
    _FALLBACK_WINDOW_DAYS,
)

CHAT_ID = -100
DAY = 86400
_ANS = ('{"beliefs":[{"text":"вася всегда платит за всех",'
        '"evidence":[1,2]}]}')
_LOGGER_NAME = "services.dream_worker"


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


class _FakeLLM:
    def __init__(self, *answers):
        self._answers = list(answers)
        self.calls = []

    async def generate(self, messages, temperature=None):
        self.calls.append(messages)
        if self._answers:
            return self._answers.pop(0)
        return '{"beliefs":[]}'


class _FakeHotCache:
    def __init__(self, values):
        self._values = dict(values or {})

    def get(self, key, default=None):
        return self._values.get(key, default)


def _hot(monkeypatch, values=None):
    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


def _worker(db, llm, monkeypatch):
    _hot(monkeypatch, {"memory.dream_enabled": True})
    return DreamWorker(db, memory=None, llm=llm)


async def _add_fact(db, text, *, importance=4):
    return await db.insert_graph_fact(CHAT_ID, text, "chat_history", None,
                                      importance=importance)


async def _weak_topic(db):
    await _add_fact(db, "вася платит деньги в баре раз", importance=4)
    await _add_fact(db, "вася платит деньги в баре два", importance=4)


def test_fallback_constants_smoke():
    assert _FALLBACK_WINDOW_DAYS == 3
    assert _FALLBACK_MIN_CLUSTER_SIZE == 2
    assert _FALLBACK_MIN_IMPORTANCE_SUM == 8


class TestSleepSmoke:
    @pytest.mark.asyncio
    async def test_idle_fallback_synthesizes_weak_cluster(self, db,
                                                          monkeypatch):
        llm = _FakeLLM(_ANS)
        w = _worker(db, llm, monkeypatch)
        assert await w._sleep_fallback_active(int(time.time())) is True
        await _weak_topic(db)
        res = await w.run_once(CHAT_ID)
        assert res["status"] == "ok" and res["distilled"] == 1
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE kind = 'belief'")
        assert (await cursor.fetchone())["c"] == 1

    @pytest.mark.asyncio
    async def test_self_heals_after_synthesis(self, db, monkeypatch):
        llm = _FakeLLM(_ANS)
        w = _worker(db, llm, monkeypatch)
        await _weak_topic(db)
        assert (await w.run_once(CHAT_ID))["distilled"] == 1
        await _add_fact(db, "петя купил новую машину раз", importance=4)
        await _add_fact(db, "петя купил новую машину два", importance=4)
        res2 = await w.run_once(CHAT_ID)
        assert res2["distilled"] == 0          # база 3/Σ12 отсекла слабый
        assert len(llm.calls) == 1

    @pytest.mark.asyncio
    async def test_detect_fail_safe_on_db_error(self, db, monkeypatch):
        w = _worker(db, _FakeLLM(), monkeypatch)

        async def _boom(*a, **kw):
            raise RuntimeError("db down")

        monkeypatch.setattr(db, "last_run_at", _boom)
        assert await w._sleep_fallback_active(int(time.time())) is False

    @pytest.mark.asyncio
    async def test_sleep_log_visible_in_ring(self, db, monkeypatch):
        from services.log_ring import log_ring
        target = logging.getLogger(_LOGGER_NAME)
        old_level = target.level
        target.addHandler(log_ring)
        target.setLevel(logging.WARNING)
        try:
            w = _worker(db, _FakeLLM(_ANS), monkeypatch)
            # свежий синтез → базовые 3/Σ12 → слабый кластер скипается (WARNING)
            await db.log_dream_event(CHAT_ID, int(time.time()) - DAY,
                                     kind="distilled", status="ok")
            await _weak_topic(db)
            await w.run_once(CHAT_ID)
        finally:
            target.removeHandler(log_ring)
            target.setLevel(old_level)
        entries = log_ring.get_entries("ERROR+WARNING")
        assert any("[Sleep]" in e["message"] for e in entries)
