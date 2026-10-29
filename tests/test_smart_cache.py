"""Smart Cache — утилиты, маркерное TTL-хранилище, устойчивость к блокировкам.

EVOL-031 (30.10.2026): Exact Match Cache готовых LLM-ответов выведен из
эксплуатации (replay ответов удалён по продуктовому решению владельца).
Методы get/set/get_dedup/set_dedup и слаги search/web/youtube/direct_dedup
не существуют; живой контракт модуля: normalize_url/normalize_text/build_key
(защищённые утилиты), update-identity маркеры и wide-context срезы через
get_update_marker/set_update_marker (явный TTL), F17 lock-resilience.
Retirement-контракты см. tests/test_evol031_smart_cache_retirement.py.
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
        k2 = build_key("factcheck_wide_context", "проверь заявление")
        assert k1 != k2

    def test_same_input_same_key(self):
        assert build_key("factcheck", "  КАК Дела  ") == \
            build_key("factcheck", "как дела")

    def test_unknown_slug_raises(self):
        with pytest.raises(ValueError):
            build_key("bogus", "x")


class TestSmartCacheStorage:
    """Маркер Mechanics: roundtrip/expiry/ленивая чистка/fail-open — через
    update-marker API с явным TTL (после EVOL-031 это единственный путь
    записи; ответных get/set больше нет)."""

    @pytest_asyncio.fixture
    async def cache(self, tmp_path):
        c = SmartCache(str(tmp_path / "cache.db"))
        yield c
        await c.close()                     # L4: не оставлять aiosqlite-хвост

    @pytest.mark.asyncio
    async def test_set_get_roundtrip(self, cache):
        key = "direct_update\x00roundtrip"
        assert await cache.get_update_marker(key, ttl_seconds=60) is None
        await cache.set_update_marker(key, "1", ttl_seconds=60)
        assert await cache.get_update_marker(key, ttl_seconds=60) == "1"

    @pytest.mark.asyncio
    async def test_miss_logged(self, cache, caplog):
        with caplog.at_level(logging.INFO):
            assert await cache.get_update_marker(
                "direct_update\x00miss", ttl_seconds=60) is None
        assert any("smart cache: miss" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_expired_returns_none_and_deletes(self, cache, monkeypatch, caplog):
        clock = {"now": 1000.0}
        monkeypatch.setattr("services.smart_cache.time.monotonic", lambda: clock["now"])
        key = "direct_update\x00expired"
        await cache.set_update_marker(key, "старый маркер", ttl_seconds=60)
        clock["now"] = 1005.0
        with caplog.at_level(logging.INFO):
            assert await cache.get_update_marker(key, ttl_seconds=1) is None
        assert any("smart cache: expired" in r.message for r in caplog.records)
        # просроченная строка удалена: даже при большом TTL больше не отдаётся
        assert await cache.get_update_marker(key, ttl_seconds=3600) is None

    @pytest.mark.asyncio
    async def test_lazy_cleanup_over_max_rows(self, cache, monkeypatch):
        small = replace(settings, SMART_CACHE_MAX_ROWS=5)
        monkeypatch.setattr("services.smart_cache.settings", small)
        for i in range(10):
            await cache.set_update_marker(f"key-{i}", f"маркер {i}",
                                          ttl_seconds=3600)
        assert await cache.get_update_marker("key-0", ttl_seconds=3600) is None
        assert await cache.get_update_marker("key-9", ttl_seconds=3600) == "маркер 9"
        assert await cache.get_update_marker("key-5", ttl_seconds=3600) == "маркер 5"

    @pytest.mark.asyncio
    async def test_db_error_returns_none(self, cache, monkeypatch, caplog):
        def broken_connect(*args, **kwargs):
            raise Exception("нет файла")

        monkeypatch.setattr("services.smart_cache.aiosqlite.connect", broken_connect)
        with caplog.at_level(logging.WARNING):
            assert await cache.get_update_marker(
                "direct_update\x00boom", ttl_seconds=60) is None   # fail-open
        assert any("smart cache: DB init failed" in r.message for r in caplog.records)


class TestCacheHitInHandlers:
    """R51-4б: 2-й вызов с тем же URL/текстом НЕ дергает сервис
    (LLM/Tavily/Trafilatura не вызываются — моки)."""

    @pytest.mark.asyncio
    async def test_factcheck_second_call_runs_fresh_check(self, tmp_path, monkeypatch):
        """P0-FACTCHECK-CORRECTIVE (§6, решение владельца 28.10.2026): кеш
        готовых вердиктов Fact-check удалён — второй вызов с тем же текстом
        выполняет НОВУЮ проверку (актуальный сервисный вызов и свежий
        ответ), старый вердикт не отдаётся. SmartCache других подсистем
        (web — ниже) не затронут."""
        import handlers.factcheck as fc_mod

        monkeypatch.setattr(
            "services.smart_cache.settings",
            replace(settings, SMART_CACHE_ENABLED=True),
        )
        monkeypatch.setattr(
            "services.mca_gates.temporal_factcheck_enabled",
            lambda: False)
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
            # второй вызов с тем же контентом → НОВАЯ проверка (кеша нет);
            # свежий вердикт отвечает на ЦЕЛЕВОЕ сообщение (5.4b)
            fc_mod._cooldown._last.clear()
            service.check_claim = AsyncMock(return_value="вердикт два")
            msg2 = _fc_message(target_text="та же ссылка", message_id=22)
            await fc_mod.factcheck_handler(msg2, bot=bot)
            assert service.check_claim.await_count == 1
            assert bot.send_message.await_args.kwargs["reply_to_message_id"] == 1
            assert bot.send_message.await_args.args[1] == "вердикт два"
        finally:
            fc_mod.setup_factcheck(None)
            fc_mod._cooldown._last.clear()
            await real_cache.close()

    @pytest.mark.asyncio
    async def test_web_second_call_runs_service_again(self):
        """EVOL-031: кеш готовых ответов удалён — второй вызов с той же
        ссылкой (и с тем же нормализованным URL) ОБЯЗАН снова дёрнуть сервис
        (свежая выжимка, реплея нет)."""
        import handlers.web as web_mod

        service = MagicMock()
        service.summarize = AsyncMock(return_value="свежая выжимка")
        web_mod.setup_web(service)
        bot = AsyncMock()
        try:
            msg = _url_message("Бот, поясни за ссылку https://site.ru/article")
            await web_mod.web_handler(msg, bot=bot)
            assert service.summarize.await_count == 1
            # та же ссылка с utm-хвостом → в старом EMC был бы cache-hit
            web_mod._cooldown._last.clear()
            msg2 = _url_message(
                "Бот, выжимка https://site.ru/article?utm_source=x", message_id=33)
            await web_mod.web_handler(msg2, bot=bot)
            assert service.summarize.await_count == 2   # живой путь, не реплей
            assert bot.send_message.await_count == 2
        finally:
            web_mod.setup_web(None)
            web_mod._cooldown._last.clear()


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


# EVOL-031: класс TestDirectDedupCache (дедуп-неймспейс direct_dedup, Epic 60
# 67.4) удалён вместе с самой фичей — replay-ветки и её API больше нет.
# Retirement-контракты: tests/test_evol031_smart_cache_retirement.py.


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
    async def cache(self, tmp_path):
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
        key = "direct_update\x00retry"
        with caplog.at_level(logging.INFO):
            await cache.set_update_marker(key, "маркер после ретраев",
                                          ttl_seconds=60)
        assert proxy.attempts == 3          # 2 сбоя + 1 успех
        assert proxy._remaining == 0
        assert "smart_cache_lock_exhausted" not in caplog.text
        cache._db = real
        assert await cache.get_update_marker(key, ttl_seconds=60) == \
            "маркер после ретраев"

    @pytest.mark.asyncio
    async def test_write_lock_exhausted_is_explicit(self, cache, monkeypatch, caplog):
        """(c) исчерпание: fail-open + структурный WARNING + счётчик."""
        monkeypatch.setattr("services.smart_cache._LOCK_BACKOFF", 0)
        real = await cache._ensure_db()
        proxy = _FlakyDB(real, marker="INSERT OR REPLACE", fail_times=99)
        cache._db = proxy
        key = "direct_update\x00boom"
        before = smart_cache_lock_exhausted_total()
        with caplog.at_level(logging.WARNING):
            await cache.set_update_marker(key, "СЕКРЕТНЫЙ-PAYLOAD",
                                          ttl_seconds=60)   # не должно бросать
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
            assert await cache.get_update_marker(
                "direct_update\x00none", ttl_seconds=60) is None
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
            await cache.set_update_marker("k", "v", ttl_seconds=60)  # fail-open
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
        c = SmartCache(str(tmp_path / "off_retry.db"))
        try:
            real = await c._ensure_db()
            proxy = _FlakyDB(real, marker="INSERT OR REPLACE", fail_times=99)
            c._db = proxy
            before = smart_cache_lock_exhausted_total()
            with caplog.at_level(logging.WARNING):
                await c.set_update_marker("direct_update\x00off", "v",
                                          ttl_seconds=60)
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
