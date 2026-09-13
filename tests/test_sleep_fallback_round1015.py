"""F3 round1015 (`sleep-unblock-diagnostics-round1015`) — разблокировка Сна.

Покрытие (spec §8):
- детект «0 убеждений за 3 дня» (`_sleep_fallback_active`, fail-safe);
- динамические пороги 2/8 при активном fallback и базовые 3/12 иначе;
- самоотключение fallback после первого синтеза;
- защита от мусора: одиночный факт не проходит и в fallback;
- точный формат пре-гейт-лога `[Sleep]` (skipped — WARNING, passed — INFO);
- видимость WARNING-строки в дефолтном фильтре «Логи» (`ERROR+WARNING`).

LLM замокан; SQLite in-memory.
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
        self.calls.append((messages, temperature))
        if self._answers:
            answer = self._answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return '{"beliefs":[]}'


class _FakeHotCache:
    def __init__(self, values):
        self._values = dict(values or {})

    def get(self, key, default=None):
        return self._values.get(key, default)


def _hot(monkeypatch, values=None):
    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


def _worker(db, llm, monkeypatch):
    """Гейт dream включён (как в проде) — иначе chat скипается до гейта."""
    _hot(monkeypatch, {"memory.dream_enabled": True})
    return DreamWorker(db, memory=None, llm=llm)


async def _add_fact(db, text, *, importance=4, chat_id=CHAT_ID):
    return await db.insert_graph_fact(chat_id, text, "chat_history", None,
                                      importance=importance)


async def _seed_distilled(db, run_at, chat_id=CHAT_ID):
    await db.log_dream_event(chat_id, int(run_at), kind="distilled",
                             status="ok")


def _sleep_records(caplog):
    return [r for r in caplog.records if "[Sleep]" in r.getMessage()]


# ── 1. детект «0 убеждений за 3 дня» ─────────────────────────────────────


class TestFallbackDetect:
    @pytest.mark.asyncio
    async def test_active_when_no_distilled(self, db, monkeypatch):
        w = _worker(db, _FakeLLM(), monkeypatch)
        assert await w._sleep_fallback_active(int(time.time())) is True

    @pytest.mark.asyncio
    async def test_active_when_stale(self, db, monkeypatch):
        w = _worker(db, _FakeLLM(), monkeypatch)
        now = int(time.time())
        await _seed_distilled(db, now - (_FALLBACK_WINDOW_DAYS + 1) * DAY)
        assert await w._sleep_fallback_active(now) is True

    @pytest.mark.asyncio
    async def test_inactive_when_fresh(self, db, monkeypatch):
        w = _worker(db, _FakeLLM(), monkeypatch)
        now = int(time.time())
        await _seed_distilled(db, now - 1 * DAY)
        assert await w._sleep_fallback_active(now) is False

    @pytest.mark.asyncio
    async def test_inactive_on_db_error(self, db, monkeypatch):
        """Fail-safe (spec §9): ошибка БД → базовые пороги (False)."""
        w = _worker(db, _FakeLLM(), monkeypatch)

        async def _boom(*a, **kw):
            raise RuntimeError("db down")

        monkeypatch.setattr(db, "last_run_at", _boom)
        assert await w._sleep_fallback_active(int(time.time())) is False


def test_fallback_constants():
    """Код-константы fallback (каталог-Δ=0)."""
    assert _FALLBACK_WINDOW_DAYS == 3
    assert _FALLBACK_MIN_CLUSTER_SIZE == 2
    assert _FALLBACK_MIN_IMPORTANCE_SUM == 8


# ── 2–4. применение порогов ──────────────────────────────────────────────


async def _weak_topic(db, chat_id=CHAT_ID):
    """Кластер из 2 фактов Σ8 — в обычном гейте отброшен (членов 2 < 3)."""
    await _add_fact(db, "вася платит деньги в баре раз", importance=4,
                    chat_id=chat_id)
    await _add_fact(db, "вася платит деньги в баре два", importance=4,
                    chat_id=chat_id)


class TestFallbackGate:
    @pytest.mark.asyncio
    async def test_weak_cluster_passes_in_fallback(self, db, monkeypatch):
        """Кластер 2 факта/Σ8 проходит при «0 убеждений 3 дня»."""
        llm = _FakeLLM(_ANS)
        w = _worker(db, llm, monkeypatch)
        await _weak_topic(db)
        res = await w.run_once(CHAT_ID)
        assert res["status"] == "ok"
        assert res["distilled"] == 1
        assert len(llm.calls) == 1
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE kind = 'belief'")
        assert (await cursor.fetchone())["c"] == 1

    @pytest.mark.asyncio
    async def test_single_fact_rejected_even_in_fallback(self, db, monkeypatch):
        """Защита от мусора: единичный факт не проходит и в fallback."""
        llm = _FakeLLM(_ANS)
        w = _worker(db, llm, monkeypatch)
        await _add_fact(db, "вася платит деньги в баре раз", importance=10)
        res = await w.run_once(CHAT_ID)
        assert res["distilled"] == 0
        assert res["clusters"] == 0
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_base_rejects_weak_cluster_when_fresh(self, db, monkeypatch):
        """Свежее убеждение (< 3 дней) → базовые 3/12, кластер 2/Σ8 отброшен."""
        llm = _FakeLLM(_ANS)
        w = _worker(db, llm, monkeypatch)
        await _seed_distilled(db, int(time.time()) - 1 * DAY)
        await _weak_topic(db)
        res = await w.run_once(CHAT_ID)
        assert res["distilled"] == 0
        assert res["clusters"] == 0
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_self_heals_after_synthesis(self, db, monkeypatch):
        """После первого синтеза (`distilled` свежий) fallback выключается."""
        llm = _FakeLLM(_ANS)
        w = _worker(db, llm, monkeypatch)
        await _weak_topic(db)
        res1 = await w.run_once(CHAT_ID)
        assert res1["distilled"] == 1          # fallback активен
        # новая слабая тема во втором прогоне: last_run_at свежий → база
        await _add_fact(db, "петя купил новую машину раз", importance=4)
        await _add_fact(db, "петя купил новую машину два", importance=4)
        res2 = await w.run_once(CHAT_ID)
        assert res2["distilled"] == 0
        assert len(llm.calls) == 1


# ── 5–6/13. формат и видимость лога ──────────────────────────────────────


class TestSleepLogFormat:
    @pytest.mark.asyncio
    async def test_skipped_log_exact_format_warning(self, db, monkeypatch,
                                                    caplog):
        """skipped — WARNING, точная строка (threshold = эффективный sum)."""
        caplog.set_level(logging.WARNING)
        llm = _FakeLLM(_ANS)
        w = _worker(db, llm, monkeypatch)
        await _seed_distilled(db, int(time.time()) - 1 * DAY)  # база 3/12
        # кластер A: 3×3 = 9 (max); кластер B: 2×4 = 8; оба < 12
        for i in range(3):
            await _add_fact(db, f"вася платит деньги в баре {i + 1} раз",
                            importance=3)
        for i in range(2):
            await _add_fact(db, f"сон снился ночью {i + 1} раз", importance=4)
        res = await w.run_once(CHAT_ID)
        assert res["distilled"] == 0
        assert llm.calls == []
        records = _sleep_records(caplog)
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        assert records[0].getMessage() == (
            "[Sleep] Chunks: 5, Clusters formed: 2, Max importance: 9 "
            "-> Skipped (threshold 12)")

    @pytest.mark.asyncio
    async def test_passed_log_exact_format_info(self, db, monkeypatch, caplog):
        """passed — INFO, порог 12 (базовый путь)."""
        caplog.set_level(logging.INFO)
        llm = _FakeLLM(_ANS)
        w = _worker(db, llm, monkeypatch)
        await _seed_distilled(db, int(time.time()) - 1 * DAY)
        for i in range(3):
            await _add_fact(db, f"вася платит деньги в баре {i + 1} раз",
                            importance=4)
        res = await w.run_once(CHAT_ID)
        assert res["distilled"] == 1
        records = _sleep_records(caplog)
        assert len(records) == 1
        assert records[0].levelno == logging.INFO
        assert records[0].getMessage() == (
            "[Sleep] Chunks: 3, Clusters formed: 1, Max importance: 12 "
            "-> Passed (threshold 12)")

    @pytest.mark.asyncio
    async def test_passed_log_prints_fallback_threshold(self, db, monkeypatch,
                                                        caplog):
        """В fallback `threshold` = 8 (эффективный sum_min)."""
        caplog.set_level(logging.INFO)
        w = _worker(db, _FakeLLM(_ANS), monkeypatch)
        await _weak_topic(db)
        await w.run_once(CHAT_ID)
        line = _sleep_records(caplog)[0].getMessage()
        assert line == (
            "[Sleep] Chunks: 2, Clusters formed: 1, Max importance: 8 "
            "-> Passed (threshold 8)")

    @pytest.mark.asyncio
    async def test_sleep_warning_visible_in_log_ring(self, db, monkeypatch):
        """WARNING `[Sleep]` виден в дефолтном фильтре «Логи» (ERROR+WARNING)."""
        from services.log_ring import log_ring
        target = logging.getLogger(_LOGGER_NAME)
        old_level = target.level
        target.addHandler(log_ring)
        target.setLevel(logging.WARNING)
        try:
            w = _worker(db, _FakeLLM(_ANS), monkeypatch)
            await _seed_distilled(db, int(time.time()) - 1 * DAY)
            await _weak_topic(db)
            await w.run_once(CHAT_ID)
        finally:
            target.removeHandler(log_ring)
            target.setLevel(old_level)
        entries = log_ring.get_entries("ERROR+WARNING")
        assert any("[Sleep]" in e["message"] for e in entries)
