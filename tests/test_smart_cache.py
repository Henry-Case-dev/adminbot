"""Epic 51 (R51-1/R51-4, Section 59.2, D208/D209/D210): Exact Match Cache.

normalize_url/normalize_text/build_key (D208); hit/miss/expiry; ленивая
очистка; SMART_CACHE_ENABLED=False → no-op; ошибки БД → WARNING + miss;
2-й вызов с тем же URL → LLM/Tavily/Trafilatura НЕ вызываются (мок хендлера).
"""
import logging
import sqlite3
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from config.settings import settings
from services.smart_cache import (
    SmartCache,
    build_key,
    normalize_text,
    normalize_url,
    smart_cache_lock_exhausted_total,
)

CHAT_ID = -1001234567890


class TestNormalizeUrl:
    def test_utm_params_stripped(self):
        a = normalize_url("https://Site.Ru/page?utm_source=x&utm_medium=y&id=5")
        b = normalize_url("https://site.ru/page?id=5")
        assert a == b == "https://site.ru/page?id=5"

    def test_fbclid_gclid_stripped(self):
        a = normalize_url("https://site.ru/p?a=1&fbclid=xyz&gclid=abc")
        assert a == "https://site.ru/p?a=1"

    def test_trailing_slash_and_host_case(self):
        assert normalize_url("HTTPS://Example.COM/path/") == "https://example.com/path"
        assert normalize_url("https://example.com/") == "https://example.com/"  # корень: slash не режется

    def test_fragment_dropped(self):
        a = normalize_url("https://site.ru/p?a=1#section")
        assert a == "https://site.ru/p?a=1"
        assert "#" not in a


class TestNormalizeText:
    def test_casefold_and_collapse(self):
        assert normalize_text("  Что??  ") == "что??"
        assert normalize_text("a   b\t\n c") == "a b c"


class TestBuildKey:
    def test_slug_included_so_services_do_not_collide(self):
        k1 = build_key("factcheck", "проверь заявление")
        k2 = build_key("search", "проверь заявление")
        assert k1 != k2

    def test_same_input_same_key(self):
        assert build_key("search", "  КАК Дела  ") == build_key("search", "как дела")

    def test_unknown_slug_raises(self):
        with pytest.raises(ValueError):
            build_key("bogus", "x")


class TestSmartCacheStorage:
    @pytest_asyncio.fixture
    async def cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "services.smart_cache.settings",
            replace(settings, SMART_CACHE_ENABLED=True, SMART_CACHE_TTL_SECONDS=60),
        )
        c = SmartCache(str(tmp_path / "cache.db"))
        yield c
        await c.close()                     # L4: не оставлять aiosqlite-хвост

    @pytest.mark.asyncio
    async def test_set_get_roundtrip(self, cache):
        key = build_key("web", "https://site.ru/a")
        assert await cache.get(key) is None
        await cache.set(key, "выжимка страницы")
        assert await cache.get(key) == "выжимка страницы"

    @pytest.mark.asyncio
    async def test_miss_logged(self, cache, caplog):
        with caplog.at_level(logging.INFO):
            assert await cache.get(build_key("web", "https://x.ru")) is None
        assert any("smart cache: miss" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_expired_returns_none_and_deletes(self, cache, monkeypatch, caplog):
        clock = {"now": 1000.0}
        monkeypatch.setattr("services.smart_cache.time.monotonic", lambda: clock["now"])
        key = build_key("web", "https://site.ru/b")
        await cache.set(key, "старый ответ")             # created_at = 1000.0
        monkeypatch.setattr(
            "services.smart_cache.settings",
            replace(settings, SMART_CACHE_ENABLED=True, SMART_CACHE_TTL_SECONDS=1),
        )
        clock["now"] = 1005.0
        with caplog.at_level(logging.INFO):
            assert await cache.get(key) is None
        assert any("smart cache: expired" in r.message for r in caplog.records)
        # просроченная строка удалена: даже при большом TTL больше не отдаётся
        monkeypatch.setattr(
            "services.smart_cache.settings",
            replace(settings, SMART_CACHE_ENABLED=True, SMART_CACHE_TTL_SECONDS=3600),
        )
        assert await cache.get(key) is None

    @pytest.mark.asyncio
    async def test_disabled_is_noop(self, tmp_path, monkeypatch):
        from pathlib import Path

        monkeypatch.setattr(
            "services.smart_cache.settings",
            replace(settings, SMART_CACHE_ENABLED=False),
        )
        db_file = tmp_path / "disabled.db"
        c = SmartCache(str(db_file))
        assert await c.get("k") is None
        await c.set("k", "v")
        assert await c.get("k") is None
        assert not db_file.exists()      # REVISE S2: БД НЕ создаётся (no-op)
        await c.close()

    @pytest.mark.asyncio
    async def test_lazy_cleanup_over_max_rows(self, cache, monkeypatch):
        small = replace(settings, SMART_CACHE_ENABLED=True,
                        SMART_CACHE_TTL_SECONDS=3600, SMART_CACHE_MAX_ROWS=5)
        monkeypatch.setattr("services.smart_cache.settings", small)
        for i in range(10):
            await cache.set(f"key-{i}", f"ответ {i}")
        assert await cache.get("key-0") is None          # старейшие удалены
        assert await cache.get("key-9") == "ответ 9"
        assert await cache.get("key-5") == "ответ 5"

    @pytest.mark.asyncio
    async def test_db_error_returns_none(self, cache, monkeypatch, caplog):
        def broken_connect(*args, **kwargs):
            raise Exception("нет файла")

        monkeypatch.setattr("services.smart_cache.aiosqlite.connect", broken_connect)
        with caplog.at_level(logging.WARNING):
            assert await cache.get("k") is None        # miss, НЕ роняет хендлер
        assert any("smart cache: DB init failed" in r.message for r in caplog.records)


class TestCacheHitInHandlers:
    """R51-4б: 2-й вызов с тем же URL/текстом НЕ дергает сервис
    (LLM/Tavily/Trafilatura не вызываются — моки)."""

    @pytest.mark.asyncio
    async def test_factcheck_second_call_served_from_cache(self, tmp_path, monkeypatch):
        import handlers.factcheck as fc_mod

        monkeypatch.setattr(
            "services.smart_cache.settings",
            replace(settings, SMART_CACHE_ENABLED=True),
        )
        real_cache = SmartCache(str(tmp_path / "fc.db"))
        monkeypatch.setattr(fc_mod, "get_smart_cache", lambda: real_cache)
        try:
            service = MagicMock()
            service.check_claim = AsyncMock(return_value="вердикт один")
            fc_mod.setup_factcheck(service)
            bot = AsyncMock()
            msg = _fc_message(target_text="та же ссылка")
            await fc_mod.factcheck_handler(msg, bot=bot)
            assert service.check_claim.await_count == 1
            # второй вызов с тем же контентом → кэш-хит, сервис НЕ вызван
            fc_mod._cooldown._last.clear()
            msg2 = _fc_message(target_text="та же ссылка", message_id=22)
            await fc_mod.factcheck_handler(msg2, bot=bot)
            assert service.check_claim.await_count == 1
            assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 22
            assert bot.send_message.await_args.args[1] == "вердикт один"
        finally:
            fc_mod.setup_factcheck(None)
            fc_mod._cooldown._last.clear()
            await real_cache.close()

    @pytest.mark.asyncio
    async def test_web_second_call_does_not_call_service(self, tmp_path, monkeypatch):
        import handlers.web as web_mod

        monkeypatch.setattr(
            "services.smart_cache.settings",
            replace(settings, SMART_CACHE_ENABLED=True),
        )
        real_cache = SmartCache(str(tmp_path / "web.db"))
        monkeypatch.setattr(web_mod, "get_smart_cache", lambda: real_cache)
        try:
            service = MagicMock()
            service.summarize = AsyncMock(return_value="выжимка сайта")
            web_mod.setup_web(service)
            bot = AsyncMock()
            msg = _url_message("Бот, поясни за ссылку https://site.ru/article")
            await web_mod.web_handler(msg, bot=bot)
            assert service.summarize.await_count == 1
            # та же ссылка с utm-хвостом → тот же ключ → кэш-хит
            web_mod._cooldown._last.clear()
            msg2 = _url_message(
                "Бот, выжимка https://site.ru/article?utm_source=x", message_id=33)
            await web_mod.web_handler(msg2, bot=bot)
            assert service.summarize.await_count == 1   # Tavily/Trafilatura/LLM не вызваны
            assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 33
            assert bot.send_message.await_args.args[1] == "выжимка сайта"
        finally:
            web_mod.setup_web(None)
            web_mod._cooldown._last.clear()
            await real_cache.close()


def _fc_message(target_text="тест", message_id=11, chat_id=CHAT_ID):
    target = MagicMock()
    target.text = target_text
    target.caption = None
    target.forward_origin = None
    target.message_id = 1
    msg = MagicMock()
    msg.text = f"фактчек {target_text}"
    msg.caption = None
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.id = 10
    msg.reply_to_message = target
    msg.forward_origin = None
    return msg


def _url_message(text="Бот, выжимка https://site.ru/article", message_id=11,
                 chat_id=CHAT_ID):
    msg = MagicMock()
    msg.text = text
    msg.caption = None
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.id = 10
    msg.reply_to_message = None
    msg.forward_origin = None
    return msg


class TestDirectDedupCache:
    """Epic 60 Фаза E (67.4, T-499): дедуп-неймспейс direct_dedup.
    Свой рубильник CHAT_DEDUP_ENABLED и свой TTL; SMART_CACHE_ENABLED=False
    дедуп НЕ выключает (разные фичи)."""

    @pytest.fixture
    def cache(self, tmp_path):
        return SmartCache(str(tmp_path / "dedup.db"))

    def test_direct_dedup_slug_registered_and_normalized(self):
        assert build_key("direct_dedup", "привет БОТ") == \
            build_key("direct_dedup", "  привет бот  ")

    def test_slug_does_not_collide_with_other_services(self):
        assert build_key("direct_dedup", "x") != build_key("search", "x")

    @pytest.mark.asyncio
    async def test_roundtrip_and_empty_marker(self, cache):
        key = build_key("direct_dedup", "привет бот")
        assert await cache.get_dedup(key) is None          # первый раз
        await cache.set_dedup(key, "")                     # маркер «ответа не было»
        assert await cache.get_dedup(key) == ""
        await cache.set_dedup(key, "ответ из кэша")
        assert await cache.get_dedup(key) == "ответ из кэша"
        await cache.close()

    @pytest.mark.asyncio
    async def test_own_ttl_expiry(self, cache, monkeypatch):
        clock = {"now": 1000.0}
        monkeypatch.setattr("services.smart_cache.time.monotonic",
                            lambda: clock["now"])
        monkeypatch.setattr(
            "services.smart_cache.settings",
            replace(settings, CHAT_DEDUP_TTL_SECONDS=10))
        key = build_key("direct_dedup", "тот же текст")
        await cache.set_dedup(key, "ответ")
        clock["now"] += 5
        assert await cache.get_dedup(key) == "ответ"
        clock["now"] += 6                                  # > TTL 10с
        assert await cache.get_dedup(key) is None
        await cache.close()

    @pytest.mark.asyncio
    async def test_disabled_flag_is_noop(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "services.smart_cache.settings",
            replace(settings, CHAT_DEDUP_ENABLED=False))
        db_file = tmp_path / "off.db"
        c = SmartCache(str(db_file))
        assert await c.get_dedup("k") is None
        await c.set_dedup("k", "v")
        assert await c.get_dedup("k") is None
        assert not db_file.exists()                        # БД НЕ создаётся
        await c.close()

    @pytest.mark.asyncio
    async def test_works_when_smart_cache_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "services.smart_cache.settings",
            replace(settings, SMART_CACHE_ENABLED=False))
        c = SmartCache(str(tmp_path / "mix.db"))
        key = build_key("direct_dedup", "текст")
        await c.set_dedup(key, "ответ мимо глобального рубильника")
        assert await c.get_dedup(key) == "ответ мимо глобального рубильника"
        # обычный Exact Match Cache при этом остаётся выключен
        assert await c.get(key) is None
        await c.set(key, "v")
        assert await c.get(key) is None
        await c.close()

    @pytest.mark.asyncio
    async def test_feature_flags_independent_both_directions(
            self, tmp_path, monkeypatch):
        """T-506: рубильники фич независимы в ОБЕ стороны:
        SMART_CACHE_ENABLED=False + CHAT_DEDUP_ENABLED=True → dedup живёт,
        обычный кэш мёртв; SMART_CACHE_ENABLED=True + CHAT_DEDUP_ENABLED=False
        → dedup мёртв, обычный кэш живёт."""
        key = build_key("direct_dedup", "текст")

        monkeypatch.setattr(
            "services.smart_cache.settings",
            replace(settings, SMART_CACHE_ENABLED=False,
                    CHAT_DEDUP_ENABLED=True))
        c1 = SmartCache(str(tmp_path / "dedup_alive.db"))
        await c1.set_dedup(key, "дедуп жив")
        assert await c1.get_dedup(key) == "дедуп жив"
        assert await c1.get("k") is None            # EMC заглушен
        await c1.close()

        monkeypatch.setattr(
            "services.smart_cache.settings",
            replace(settings, SMART_CACHE_ENABLED=True,
                    CHAT_DEDUP_ENABLED=False))
        c2 = SmartCache(str(tmp_path / "emc_alive.db"))
        await c2.set("k", "обычный жив")
        assert await c2.get("k") == "обычный жив"
        await c2.set_dedup(key, "не сохранится")
        assert await c2.get_dedup(key) is None      # dedup заглушен
        await c2.close()


class _FlakyDB:
    """Обёртка над реальным aiosqlite-соединением: первые `fail_times`
    вызовов `execute` с подстрокой `marker` падают `OperationalError: locked`.

    Нужна для проверки bounded retry без гонки за реальной блокировкой."""

    def __init__(self, real, *, marker: str, fail_times: int):
        self._real = real
        self._marker = marker
        self._remaining = fail_times
        self.attempts = 0

    async def execute(self, sql, *args, **kwargs):
        if self._marker in sql:
            self.attempts += 1
            if self._remaining > 0:
                self._remaining -= 1
                raise sqlite3.OperationalError("database is locked")
        return await self._real.execute(sql, *args, **kwargs)

    async def commit(self):
        return await self._real.commit()

    async def rollback(self):
        return await self._real.rollback()

    async def close(self):
        return await self._real.close()


class _BoomDB:
    """Соединение, падающее НЕ-lock ошибкой на любом execute."""

    def __init__(self):
        self.attempts = 0

    async def execute(self, sql, *args, **kwargs):
        self.attempts += 1
        raise sqlite3.OperationalError("attempt to write a readonly database")

    async def commit(self):
        return None

    async def rollback(self):
        return None

    async def close(self):
        return None


class TestLockResilience:
    """F17 (раунд 10.24, ADR-1024-18): PRAGMA-паритет + bounded retry."""

    @pytest_asyncio.fixture
    async def cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "services.smart_cache.settings",
            replace(settings, SMART_CACHE_ENABLED=True,
                    SMART_CACHE_TTL_SECONDS=60),
        )
        c = SmartCache(str(tmp_path / "resilience.db"))
        yield c
        await c.close()

    @pytest.mark.asyncio
    async def test_pragmas_applied(self, cache):
        """(a) WAL/busy_timeout/synchronous реально применены (файловая БД)."""
        db = await cache._ensure_db()
        assert db is not None
        cur = await db.execute("PRAGMA journal_mode")
        assert str((await cur.fetchone())[0]).lower() == "wal"
        cur = await db.execute("PRAGMA busy_timeout")
        assert int((await cur.fetchone())[0]) == 5000
        cur = await db.execute("PRAGMA synchronous")
        assert int((await cur.fetchone())[0]) == 1  # NORMAL

    @pytest.mark.asyncio
    async def test_write_retry_then_success(self, cache, monkeypatch, caplog):
        """(b) locked на первых попытках → retry сохраняет запись, без события."""
        monkeypatch.setattr("services.smart_cache._LOCK_BACKOFF", 0)
        real = await cache._ensure_db()
        proxy = _FlakyDB(real, marker="INSERT OR REPLACE", fail_times=2)
        cache._db = proxy
        key = build_key("web", "https://site.ru/retry")
        with caplog.at_level(logging.INFO):
            await cache.set(key, "ответ после ретраев")
        assert proxy.attempts == 3          # 2 сбоя + 1 успех
        assert proxy._remaining == 0
        assert "smart_cache_lock_exhausted" not in caplog.text
        cache._db = real
        assert await cache.get(key) == "ответ после ретраев"

    @pytest.mark.asyncio
    async def test_write_lock_exhausted_is_explicit(self, cache, monkeypatch, caplog):
        """(c) исчерпание: fail-open + структурный WARNING + счётчик."""
        monkeypatch.setattr("services.smart_cache._LOCK_BACKOFF", 0)
        real = await cache._ensure_db()
        proxy = _FlakyDB(real, marker="INSERT OR REPLACE", fail_times=99)
        cache._db = proxy
        key = build_key("web", "https://site.ru/boom")
        before = smart_cache_lock_exhausted_total()
        with caplog.at_level(logging.WARNING):
            await cache.set(key, "СЕКРЕТНЫЙ-PAYLOAD")   # не должно бросать
        assert proxy.attempts == 4          # 1 попытка + 3 повтора
        assert smart_cache_lock_exhausted_total() == before + 1
        events = [r for r in caplog.records
                  if "event=smart_cache_lock_exhausted" in r.message]
        assert events, "ожидался структурный WARNING при исчерпании"
        assert "op=set" in events[0].message
        assert f"key={key}" in events[0].message
        assert "attempts=4" in events[0].message
        assert "database is locked" in events[0].message
        # R17: payload в логах отсутствует
        assert "СЕКРЕТНЫЙ-PAYLOAD" not in caplog.text

    @pytest.mark.asyncio
    async def test_read_lock_exhausted_returns_none(self, cache, monkeypatch, caplog):
        """(c) для _read: fail-open (None) + тот же структурный WARNING."""
        monkeypatch.setattr("services.smart_cache._LOCK_BACKOFF", 0)
        real = await cache._ensure_db()
        proxy = _FlakyDB(real, marker="SELECT payload", fail_times=99)
        cache._db = proxy
        before = smart_cache_lock_exhausted_total()
        with caplog.at_level(logging.WARNING):
            assert await cache.get(build_key("web", "https://x/none")) is None
        assert proxy.attempts == 4
        assert smart_cache_lock_exhausted_total() == before + 1
        assert any("op=get" in r.message and "event=smart_cache_lock_exhausted" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_non_lock_error_not_retried(self, cache, monkeypatch, caplog):
        """(f) не-lock исключение — одна попытка, прежний WARNING."""
        monkeypatch.setattr("services.smart_cache._LOCK_BACKOFF", 0)
        real = await cache._ensure_db()
        boom = _BoomDB()
        cache._db = boom
        before = smart_cache_lock_exhausted_total()
        with caplog.at_level(logging.WARNING):
            await cache.set("k", "v")        # fail-open, не бросает
        assert boom.attempts == 1
        assert smart_cache_lock_exhausted_total() == before
        assert any("smart cache: set failed" in r.message for r in caplog.records)
        assert "smart_cache_lock_exhausted" not in caplog.text
        cache._db = real                     # вернуть реальное соединение (fixture)

    @pytest.mark.asyncio
    async def test_flag_off_no_pragmas(self, tmp_path, monkeypatch):
        """(e) kill-switch: PRAGMA не применяются."""
        calls = []

        async def spy(db):
            calls.append(db)

        monkeypatch.setattr("services.smart_cache._apply_pragmas", spy)
        monkeypatch.setattr("services.smart_cache._resilience_enabled", lambda: False)
        c = SmartCache(str(tmp_path / "off.db"))
        try:
            db = await c._ensure_db()
            assert calls == []                          # PRAGMA не вызывались
            cur = await db.execute("PRAGMA journal_mode")
            assert str((await cur.fetchone())[0]).lower() != "wal"
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_flag_off_single_attempt(self, tmp_path, monkeypatch, caplog):
        """(e) kill-switch: при `locked` одна попытка и прежний WARNING."""
        monkeypatch.setattr("services.smart_cache._resilience_enabled", lambda: False)
        monkeypatch.setattr("services.smart_cache._LOCK_BACKOFF", 0)
        monkeypatch.setattr(
            "services.smart_cache.settings",
            replace(settings, SMART_CACHE_ENABLED=True,
                    SMART_CACHE_TTL_SECONDS=60),
        )
        c = SmartCache(str(tmp_path / "off_retry.db"))
        try:
            real = await c._ensure_db()
            proxy = _FlakyDB(real, marker="INSERT OR REPLACE", fail_times=99)
            c._db = proxy
            before = smart_cache_lock_exhausted_total()
            with caplog.at_level(logging.WARNING):
                await c.set(build_key("web", "https://off/x"), "v")
            assert proxy.attempts == 1
            assert smart_cache_lock_exhausted_total() == before
            assert any("smart cache: set failed" in r.message for r in caplog.records)
            assert "smart_cache_lock_exhausted" not in caplog.text
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_init_failure_closes_connection(self, tmp_path, monkeypatch):
        """(g) провал инициализации → соединение закрыто, self._db is None."""
        import aiosqlite

        captured = []
        real_connect = aiosqlite.connect

        async def capturing_connect(path):
            conn = await real_connect(path)
            captured.append(conn)
            return conn

        async def boom_pragmas(db):
            raise RuntimeError("pragma fail")

        monkeypatch.setattr("services.smart_cache.aiosqlite.connect", capturing_connect)
        monkeypatch.setattr("services.smart_cache._apply_pragmas", boom_pragmas)
        c = SmartCache(str(tmp_path / "fd.db"))
        assert await c._ensure_db() is None
        assert c._db is None
        assert len(captured) == 1
        assert captured[0]._connection is None      # aiosqlite.close() обнуляет
        # после снятия поломки повторная инициализация возможна и корректна
        async def ok_pragmas(db):
            return None

        monkeypatch.setattr("services.smart_cache._apply_pragmas", ok_pragmas)
        assert await c._ensure_db() is not None
        await c.close()
