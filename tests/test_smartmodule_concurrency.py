"""Раунд N (T-839/T-842): ChatConcurrencyPool — per-chat пул семафоров
LLM-генераций smart module (замена per-chat лока direct_chat и глобального
лока summary). Покрытие: N-параллельность, таймаут-слот, release, N=1 как
строгий лок, смена N → новые слоты, ленивая чистка переполнения (включая
pending-защиту eviction-гонки T-501), синглтон/reset.
"""
import asyncio

import pytest

import config.settings as settings_module
from services.smartmodule_concurrency import (
    ChatConcurrencyPool,
    get_smartmodule_concurrency_pool,
    reset_smartmodule_concurrency_pool,
)

CHAT_A = -1001
CHAT_B = -1002


@pytest.fixture
def pool_n(monkeypatch):
    """Задать N (и wait) для НОВЫХ пулов через settings модуля пула
    (hot-кэш в тестах не инициализирован → settings-дефолт)."""

    def _set(n: int, wait: float = 60.0):
        monkeypatch.setattr(
            "services.smartmodule_concurrency.settings",
            settings_module.Settings(
                SMARTMODULE_CONCURRENCY_PER_CHAT=n,
                SMARTMODULE_CONCURRENCY_WAIT_SECONDS=wait))
    return _set


async def _wait_done(task, ticks: int = 4) -> bool:
    """Дать циклу ticks тиков; True — задача уже завершилась."""
    for _ in range(ticks):
        if task.done():
            return True
        await asyncio.sleep(0)
    return task.done()


class TestPoolPermits:
    @pytest.mark.asyncio
    async def test_three_permits_at_once_fourth_waits(self, pool_n):
        """N=3: 3 acquire проходят сразу; 4-й ждёт, пока один release'нут."""
        pool_n(3)
        pool = ChatConcurrencyPool()
        permits = [await pool.acquire(CHAT_A) for _ in range(3)]
        fourth = asyncio.ensure_future(pool.acquire(CHAT_A))
        assert not await _wait_done(fourth)      # 4-й стоит
        permits.pop().release()
        assert await _wait_done(fourth)           # после release — прошёл
        fourth.result().release()
        for p in permits:
            p.release()
        assert pool.slot_n(CHAT_A) == 3

    @pytest.mark.asyncio
    async def test_try_acquire_timeout_returns_none(self, pool_n):
        """try_acquire с таймаутом: занятый чат → None (не блокирует)."""
        pool_n(1, wait=60.0)
        pool = ChatConcurrencyPool()
        holder = await pool.acquire(CHAT_A)
        assert await pool.try_acquire(CHAT_A, timeout=0.05) is None
        holder.release()
        permit = await pool.try_acquire(CHAT_A, timeout=0.05)
        assert permit is not None
        permit.release()

    @pytest.mark.asyncio
    async def test_double_release_safe_and_chat_isolated(self, pool_n):
        """release повторно — no-op; разные чаты не делят слоты."""
        pool_n(1)
        pool = ChatConcurrencyPool()
        permit_a = await pool.acquire(CHAT_A)
        permit_a.release()
        permit_a.release()                        # no-op
        permit_b = await pool.acquire(CHAT_B)     # чат B свободен всегда
        permit_b.release()
        assert await pool.try_acquire(CHAT_A, timeout=0.0) is not None

    @pytest.mark.asyncio
    async def test_n1_serializes_acquires(self, pool_n):
        """N=1: строгая очередь — второй acquire ждёт первого (как старый lock)."""
        pool_n(1)
        pool = ChatConcurrencyPool()
        first = await pool.acquire(CHAT_A)
        second = asyncio.ensure_future(pool.acquire(CHAT_A))
        assert not await _wait_done(second)
        first.release()
        assert await _wait_done(second)
        second.result().release()

    @pytest.mark.asyncio
    async def test_timeout_zero_probes_busy_without_wait(self, pool_n):
        """try_acquire(timeout=0) — мгновенная проба занятости (semantics
        busy-проверки summary)."""
        pool_n(1)
        pool = ChatConcurrencyPool()
        holder = await pool.acquire(CHAT_A)
        assert await pool.try_acquire(CHAT_A, timeout=0.0) is None  # занят
        holder.release()
        assert await pool.try_acquire(CHAT_A, timeout=0.0) is not None  # свободен


class TestPoolNChangeAndCleanup:
    @pytest.mark.asyncio
    async def test_n_change_replaces_slot(self, pool_n):
        """Смена N под живьём: старый слот заменяется на sem с новым N
        (держатели старого доживают на осиротевшем sem — безопасно)."""
        pool_n(1)
        pool = ChatConcurrencyPool()
        holder = await pool.acquire(CHAT_A)
        pool_n(3)
        permits = [await pool.acquire(CHAT_A) for _ in range(3)]  # новый слот N=3
        assert pool.slot_n(CHAT_A) == 3
        for p in permits:
            p.release()
        holder.release()

    @pytest.mark.asyncio
    async def test_cleanup_when_over_capacity(self, pool_n):
        """len(_slots) > max_entries → свободные слоты чистятся (лениво)."""
        pool_n(1)
        pool = ChatConcurrencyPool(max_entries=16)
        for chat in range(40):
            permit = await pool.acquire(chat)     # слот создан
            permit.release()                      # свободен → кандидат чистки
        assert pool.slot_count() <= 16
        assert await pool.acquire(CHAT_A) is not None   # свежий доступен

    @pytest.mark.asyncio
    async def test_cleanup_keeps_busy_slot(self, pool_n):
        """Занятый слот (sem._value < n) НЕ выселяется чисткой."""
        pool_n(3)
        pool = ChatConcurrencyPool(max_entries=8)
        busy = [await pool.acquire(CHAT_A) for _ in range(3)]  # слот занят
        for chat in range(1, 30):                 # перелив
            permit = await pool.acquire(chat)
            permit.release()
        assert pool._slots.get(CHAT_A) is not None
        assert pool.slot_count() <= 8
        for p in busy:
            p.release()

    @pytest.mark.asyncio
    async def test_cleanup_skips_slot_with_pending_waiter(self, pool_n):
        """T-501-регрессия eviction-гонки (порт с замков direct_chat): слот,
        из-под guard которого корутина ещё не вошла в acquire (pending>0),
        НЕ выселяется — иначе у чата появилось бы два «владельца»."""
        pool_n(1)
        pool = ChatConcurrencyPool(max_entries=8)
        victim = await pool._get_slot(CHAT_A)     # pending=1, в acquire ещё не вошла
        for chat in range(1, 40):                 # перелив → ленивая чистка
            other = await pool._get_slot(chat)
            pool._drop_pending(other)
        assert pool._slots.get(CHAT_A) is victim  # не выселен с ожидающим
        again = await pool._get_slot(CHAT_A)
        assert again is victim                    # тот же объект — один владелец
        pool._drop_pending(again)
        pool._drop_pending(victim)


class TestPoolSingleton:
    def test_singleton_same_object_and_reset(self):
        reset_smartmodule_concurrency_pool()
        pool1 = get_smartmodule_concurrency_pool()
        pool2 = get_smartmodule_concurrency_pool()
        assert pool1 is pool2
        reset_smartmodule_concurrency_pool()
        pool3 = get_smartmodule_concurrency_pool()
        assert pool3 is not pool1
        reset_smartmodule_concurrency_pool()
