"""Раунд 7 (chat-lore-management-v2, T-774, B4) — тесты ChatLoreCache.

Q2/D6: RAM-кэш профилей, load-on-demand через store, TTL-фолбэк 120 с
(тест — малый ttl), NOTIFY-инвалидация (invalidate/invalidate_all),
fail-open при ошибке store (WARNING с дедупом, None НЕ кэшируется),
коалесинг параллельных miss'ов (один SELECT), None-профиль не кэшируется.
"""
import asyncio
import logging

import pytest

from services.lore_cache import ChatLoreCache, LoreProfile


def make_profile(chat_id: int = 7, manual: str = "manual",
                 auto: str = "auto", **kw) -> LoreProfile:
    return LoreProfile(
        chat_id=chat_id,
        manual_lore=kw.get("manual_lore", manual),
        auto_lore=kw.get("auto_lore", auto),
        auto_enabled=kw.get("auto_enabled", True),
        auto_period_hours=kw.get("auto_period_hours", 24),
        auto_window_hours=kw.get("auto_window_hours", 24),
        is_active=kw.get("is_active", True),
        last_auto_at=kw.get("last_auto_at"),
        updated_at=kw.get("updated_at", "2026-09-06T10:00:00+00:00"),
    )


class _FakeStore:
    """Store-заглушка: профили по id, счётчик вызовов, сбой/задержка."""

    def __init__(self, profiles=None, *, error=None, delay: float = 0.0,
                 mutation=None):
        self.profiles = dict(profiles or {})
        self.calls: list[int] = []
        self.error = error
        self.delay = delay
        self.mutation = mutation   # callable(chat_id) — меняет выдачу

    async def get_profile(self, chat_id: int):
        self.calls.append(chat_id)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        if self.mutation is not None:
            self.mutation(chat_id)
        return self.profiles.get(chat_id)


@pytest.fixture
def cache():
    return ChatLoreCache(_FakeStore())


class TestCacheHit:
    @pytest.mark.asyncio
    async def test_load_on_demand_and_cache_hit(self):
        prof = make_profile(7)
        store = _FakeStore({7: prof})
        c = ChatLoreCache(store)
        assert await c.get(7) == prof
        assert store.calls == [7]
        assert await c.get(7) == prof       # hit — без второго SELECT
        assert store.calls == [7]
        assert c.size() == 1

    @pytest.mark.asyncio
    async def test_get_missing_profile_not_cached(self):
        store = _FakeStore({})
        c = ChatLoreCache(store)
        assert await c.get(99) is None
        assert await c.get(99) is None      # None не кэшируется → повтор
        assert store.calls == [99, 99]
        assert c.size() == 0

    @pytest.mark.asyncio
    async def test_ttl_expiry_refetches(self):
        prof = make_profile(7)
        store = _FakeStore({7: prof})
        c = ChatLoreCache(store, ttl_seconds=0.05)
        await c.get(7)
        assert store.calls == [7]
        await asyncio.sleep(0.07)           # TTL-фолбэк (NOTIFY мог потеряться)
        assert await c.get(7) == prof
        assert store.calls == [7, 7]

    @pytest.mark.asyncio
    async def test_ttl_serves_fresh_but_refreshes_stale(self):
        store = _FakeStore({7: make_profile(7, manual="v1")})
        c = ChatLoreCache(store, ttl_seconds=0.05)
        first = await c.get(7)
        assert first.manual_lore == "v1"
        store.profiles[7] = make_profile(7, manual="v2")   # изменилось в PG
        assert (await c.get(7)).manual_lore == "v1"        # TTL не истёк
        await asyncio.sleep(0.07)
        second = await c.get(7)             # stale → перечитывание
        assert second.manual_lore == "v2"


class TestInvalidation:
    @pytest.mark.asyncio
    async def test_invalidate_removes_key(self):
        prof = make_profile(7)
        store = _FakeStore({7: prof})
        c = ChatLoreCache(store)
        await c.get(7)
        assert c.size() == 1
        await c.invalidate(7)
        assert c.size() == 0
        await c.get(7)
        assert store.calls == [7, 7]        # перечитан после NOTIFY

    @pytest.mark.asyncio
    async def test_invalidate_only_target_chat(self):
        store = _FakeStore({1: make_profile(1), 2: make_profile(2)})
        c = ChatLoreCache(store)
        await c.get(1)
        await c.get(2)
        await c.invalidate(1)
        await c.get(2)                      # ключ 2 жив — без SELECT
        assert store.calls == [1, 2]

    @pytest.mark.asyncio
    async def test_invalidate_all(self):
        store = _FakeStore({1: make_profile(1), 2: make_profile(2)})
        c = ChatLoreCache(store)
        await c.get(1)
        await c.get(2)
        assert c.size() == 2
        await c.invalidate_all()
        assert c.size() == 0
        assert await c.get(1) is not None   # load-on-demand снова работает


class TestFailOpen:
    @pytest.mark.asyncio
    async def test_store_error_returns_none_and_retries(self, caplog):
        store = _FakeStore({}, error=ConnectionError("pg down"))
        c = ChatLoreCache(store)
        with caplog.at_level(logging.WARNING):
            assert await c.get(7) is None
            assert await c.get(7) is None   # ошибка не кэшируется
        assert store.calls == [7, 7]
        warns = [r for r in caplog.records if "fail-open" in r.message]
        assert len(warns) == 1              # дедуп WARNING (раз в 60 с)
        assert c.size() == 0

    @pytest.mark.asyncio
    async def test_store_error_recovers(self):
        store = _FakeStore({7: make_profile(7)}, error=OSError("down"))
        c = ChatLoreCache(store)
        assert await c.get(7) is None
        store.error = None                  # PG поднялся
        assert await c.get(7) is not None
        assert store.calls == [7, 7]


class TestCoalescing:
    @pytest.mark.asyncio
    async def test_parallel_misses_single_select(self):
        prof = make_profile(7)
        store = _FakeStore({7: prof}, delay=0.05)
        c = ChatLoreCache(store)
        results = await asyncio.gather(c.get(7), c.get(7), c.get(7))
        assert results == [prof, prof, prof]
        assert store.calls == [7]           # коалесинг: один SELECT

    @pytest.mark.asyncio
    async def test_parallel_misses_missing_chat(self):
        store = _FakeStore({}, delay=0.02)
        c = ChatLoreCache(store)
        results = await asyncio.gather(c.get(1), c.get(1))
        assert results == [None, None]
        assert store.calls == [1]

    @pytest.mark.asyncio
    async def test_concurrent_get_after_inflight_finishes(self):
        prof = make_profile(7)
        store = _FakeStore({7: prof}, delay=0.03)
        c = ChatLoreCache(store)
        first, second = await asyncio.gather(c.get(7), c.get(7))
        assert first == second == prof
        third = await c.get(7)              # уже закэширован владельцем
        assert third == prof
        assert store.calls == [7]

    @pytest.mark.asyncio
    async def test_owner_cancel_releases_waiters(self):
        """Отмена задачи-владельца не должна навсегда зависать ждущих:
        inflight-фьюча резолвится (None, fail-open), слот чистится."""
        store = _FakeStore({7: make_profile(7)}, delay=0.3)
        c = ChatLoreCache(store)
        owner_task = asyncio.create_task(c.get(7))
        await asyncio.sleep(0.02)           # владелец уже грузит (delay 0.3)
        waiter = asyncio.create_task(c.get(7))
        owner_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner_task
        result = await asyncio.wait_for(waiter, timeout=1.0)
        assert result is None               # ждущий не завис, fail-open
        assert c.size() == 0
        assert store.calls == [7]           # второй SELECT не было (слот чист)
