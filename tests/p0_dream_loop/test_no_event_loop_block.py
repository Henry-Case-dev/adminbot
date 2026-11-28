"""P0-DREAM-LOOP-BLOCK — CPU-bound MMR не должен блокировать event loop.

Инцидент 2026-11-28: deep-sleep шёл через
`mca_dream_history.select_historical_candidates → summary_memory.
retrieve_fact_candidates → _search_graph_facts → _knn_graph_facts →
_mmr_select → score → _cosine` прямо на asyncio-loop; loop_lag достиг
728 994 мс (~12 мин), HTTP/Telegram замерли.

Контракт фикса:
  * тот же набор/порядок MMR (`_mmr_select` — тот же код в потоке);
  * event loop тикает, пока идёт тяжёлый отбор;
  * при исчерпании честного бюджета — детерминированный частичный результат
    (top-by-rel) с явной пометкой, а не зависание.
"""
from __future__ import annotations

import asyncio
import math
import time

import pytest

from services import summary_memory as sm
from config.settings import settings

CHAT_ID = -100777


def _vec(seed: int, dim: int) -> list[float]:
    return [math.sin((seed + 1) * 0.37 + i * 0.11) for i in range(dim)]


class _FakeDB:
    def __init__(self, now: int):
        self.now = now
        self.rows = {}

    def row(self, fid: int) -> dict:
        if fid not in self.rows:
            self.rows[fid] = {
                "id": fid, "status": "confirmed", "weight": 0.5,
                "last_confirmed_at": self.now, "expires_at": self.now + 86400,
                "origin": "chat_history", "fact": f"факт {fid}",
                "message_timestamp": self.now - 3600,
                "created_at": self.now - 3600, "target_user": None,
                "tg_message_id": None, "forward_from": None, "importance": 1,
            }
        return self.rows[fid]

    async def get_graph_fact_records(self, ids):
        return [self.row(int(fid)) for fid in ids]

    async def touch_graph_facts(self, *args, **kwargs):
        return 0


def _memory(*, count: int, dim: int, limit: int, fetch_k: int,
            monkeypatch) -> "sm.MemoryManager":
    now = int(time.time())
    memory = sm.MemoryManager(None, None)
    memory.db = _FakeDB(now)
    ranked = [(fid, 1.0 - fid / max(1, count), _vec(fid, dim))
              for fid in range(count)]

    async def _vec_candidates(chat_id, vector, k, include_direct_reply, now_ts,
                              include_self=False, expired_only=False):
        return list(ranked[:k])

    async def _no_resurrect(*args, **kwargs):
        return 0

    memory._vec_candidates = _vec_candidates
    memory._resurrect_resonant = _no_resurrect
    # Только этот ключ нужен тесту; остальные настройки — прежние дефолты.
    monkeypatch.setattr(sm, "hot", {
        "limits.graph_mmr_fetch_k": fetch_k,
        "limits.graph_mmr_lambda": settings.GRAPH_MMR_LAMBDA,
    })
    return memory


async def _ticks_during(coro, window_s: float) -> tuple[int, object]:
    """Сколько раз loop успел проснуться, пока выполняется `coro`."""
    loop = asyncio.get_running_loop()
    ticks = 0
    task = asyncio.create_task(coro)
    end = loop.time() + window_s
    while loop.time() < end:
        await asyncio.sleep(0.005)
        ticks += 1
    result = await task
    return ticks, result


class TestLoopStaysResponsive:
    @pytest.mark.asyncio
    async def test_heavy_mmr_does_not_block_event_loop(self, monkeypatch):
        """RED на 2.58.269: во время отбора loop не тикает вовсе."""
        memory = _memory(count=200, dim=64, limit=60, fetch_k=200,
                         monkeypatch=monkeypatch)
        stats: dict = {}

        async def heavy_call():
            return await memory._knn_graph_facts(
                CHAT_ID, _vec(0, 64), 60, policy="operative", stats=stats)

        ticks, rows = await _ticks_during(heavy_call(), window_s=0.4)
        print(f"[p0-dream] loop_ticks={ticks}")
        assert len(rows) == 60
        assert "mmr_budget_exhausted" not in stats
        # Кандидат: loop продолжает тикать, пока MMR считается в потоке.
        # База: 0–1 тик (loop занят целиком всё окно).
        assert ticks >= 5, f"event loop заблокирован: ticks={ticks}"

    @pytest.mark.asyncio
    async def test_selection_is_identical_to_sync_mmr(self):
        """Тот же код в потоке → тот же набор и порядок."""
        offload = getattr(sm, "_mmr_select_offloop", None)
        assert offload is not None, "off-loop MMR wrapper отсутствует"
        sims = [(fid, 1.0 - fid / 40, _vec(fid, 8)) for fid in range(40)]
        expected = sm._mmr_select(sims, 12, 0.6)
        got = await offload(sims, 12, 0.6)
        assert got == expected

    @pytest.mark.asyncio
    async def test_budget_returns_partial_with_explicit_marker(self,
                                                               monkeypatch):
        """Бюджет исчерпан → честный частичный top-by-rel, не зависание."""
        offload = getattr(sm, "_mmr_select_offloop", None)
        assert offload is not None, "off-loop MMR wrapper отсутствует"
        original = sm._mmr_select

        def slow_mmr(sims, limit, lam):
            time.sleep(0.5)
            return original(sims, limit, lam)

        monkeypatch.setattr(sm, "_mmr_select", slow_mmr)
        monkeypatch.setattr(sm, "_MMR_SELECT_TIMEOUT_SECONDS", 0.05)
        sims = [(fid, 1.0 - fid / 100, [1.0, 0.0]) for fid in range(20)]
        stats: dict = {}
        started = time.monotonic()
        chosen = await offload(sims, 5, 0.6, stats=stats)
        elapsed = time.monotonic() - started
        expected = [item for item, _rel, _vec in
                    sorted(sims, key=lambda s: s[1], reverse=True)[:5]]
        assert chosen == expected
        assert stats.get("mmr_budget_exhausted") == 1
        assert elapsed < 0.3, f"бюджет не сработал: {elapsed:.2f}s"

    @pytest.mark.asyncio
    async def test_empty_and_small_sets_keep_behavior(self):
        offload = getattr(sm, "_mmr_select_offloop", None)
        assert offload is not None
        assert await offload([], 5, 0.6) == []
        sims = [(1, 0.9, [1.0, 0.0]), (2, 0.8, [0.0, 1.0])]
        assert await offload(sims, 5, 0.6) == [1, 2]
