"""F2 `guide-delivery-round1016` — доставка канона «Гайда по фичам» в прод-PG.

Покрытие (spec §8, T-1638/T-1639):
  * байт-канон `DEFAULT_INFO_TEXT` ↔ `info_text.md` — в test_info_service;
  * версионная идемпотентная миграция `_migrate_info_how_it_works_v1015`:
    известный слепок (в т.ч. whitespace/CRLF-дрейф) → канон + `canon_version`;
    unknown БЕЗ маркера доставки → одноразовая форс-доставка канона
    (ревью-итер.1 High F2); unknown ПОСЛЕ доставки → НЕ затирается + WARNING +
    `canon_drift`; дрейф версии при верном тексте → добивка версии; повтор →
    no-op;
  * симуляция прод-PG со старым текстом → после init PG == канон;
  * сид `_seed_info_key` проставляет `canon_version`.
"""
import logging
import types

import pytest

from services.config_cache import ConfigCache
from services.info_service import (
    DEFAULT_INFO_TEXT,
    INFO_CANON_VERSION,
    PREV_DEFAULT_INFO_TEXT,
    canon_drift,
)

INFO_KEY = "content.info_how_it_works"
ADMIN_ID = 5885953495


class _FakeConn:
    def __init__(self, settings_rows=()):
        self.queries = []
        self._settings_rows = list(settings_rows)

    async def execute(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        return None

    async def fetch(self, sql, *args):
        if "bot_settings" in sql:
            return self._settings_rows
        return []


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


class _FakePg:
    def __init__(self, conn):
        self._pool = _FakePool(conn)

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings=True):
        pass

    async def close(self):
        pass


def _settings_row(html, canon_version=None, delivered=None):
    value = {"html": html, "updated_at": "t", "updated_by": 1}
    if canon_version is not None:
        value["canon_version"] = canon_version
    if delivered is not None:
        value["canon_delivered_version"] = delivered
    return [{"key": INFO_KEY, "value": value, "category": "content"}]


def _cache(rows, monkeypatch, info_file="no_such_file_1016.md"):
    monkeypatch.setattr(
        "services.config_cache.settings",
        types.SimpleNamespace(ADMIN_USER_ID=ADMIN_ID,
                              INFO_TEXT_FILE=info_file))
    conn = _FakeConn(rows)
    return ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0), conn


def _info_inserts(conn):
    return [q for q in conn.queries
            if "INSERT INTO bot_settings" in q[0]
            and q[1] and q[1][0] == INFO_KEY]


class TestCanonMigration:
    @pytest.mark.asyncio
    async def test_prev_snapshot_auto_migrated(self, monkeypatch):
        """§8#2/#9: прод-PG со старым каноном → init → канон + canon_version."""
        cache, conn = _cache(_settings_row(PREV_DEFAULT_INFO_TEXT), monkeypatch)
        await cache.init()
        value = cache.get(INFO_KEY)
        assert value["html"] == DEFAULT_INFO_TEXT
        assert value["canon_version"] == INFO_CANON_VERSION
        assert value["updated_by"] == ADMIN_ID
        assert len(_info_inserts(conn)) == 1

    @pytest.mark.asyncio
    async def test_whitespace_crlf_drift_still_migrated(self, monkeypatch):
        """§8#4: whitespace/CRLF-дрейф прошлого канона → нормализованный матч."""
        drifted = PREV_DEFAULT_INFO_TEXT.replace("\n", "\r\n") + "\n\n   "
        cache, conn = _cache(_settings_row(drifted), monkeypatch)
        await cache.init()
        assert cache.get(INFO_KEY)["html"] == DEFAULT_INFO_TEXT
        assert len(_info_inserts(conn)) == 1

    @pytest.mark.asyncio
    async def test_idempotent_second_run_noop(self, monkeypatch):
        """§8#3: повторный init/повторный вызов миграции → no-op (идемпотентно)."""
        cache, conn = _cache(_settings_row(PREV_DEFAULT_INFO_TEXT), monkeypatch)
        await cache.init()
        inserts_before = len(_info_inserts(conn))
        assert inserts_before == 1
        await cache._migrate_info_how_it_works_v1015()
        await cache._migrate_info_how_it_works_v1015()
        assert len(_info_inserts(conn)) == inserts_before
        assert cache.get(INFO_KEY)["html"] == DEFAULT_INFO_TEXT

    @pytest.mark.asyncio
    async def test_version_drift_text_correct_fixes_version(self, monkeypatch):
        """Текст == канон, но canon_version устарел → добиваем версию (без правки html)."""
        rows = _settings_row(DEFAULT_INFO_TEXT, canon_version=1)
        cache, conn = _cache(rows, monkeypatch)
        await cache.init()
        value = cache.get(INFO_KEY)
        assert value["html"] == DEFAULT_INFO_TEXT
        assert value["canon_version"] == INFO_CANON_VERSION
        assert len(_info_inserts(conn)) == 1

    @pytest.mark.asyncio
    async def test_current_noop_without_write(self, monkeypatch):
        """Текст == канон + актуальная версия + маркер доставки → записи нет."""
        rows = _settings_row(DEFAULT_INFO_TEXT,
                             canon_version=INFO_CANON_VERSION,
                             delivered=INFO_CANON_VERSION)
        cache, conn = _cache(rows, monkeypatch)
        await cache.init()
        assert _info_inserts(conn) == []

    @pytest.mark.asyncio
    async def test_unknown_text_force_delivered_once(self, monkeypatch, caplog):
        """Ревью-итер.1 (High F2): неизвестный прод-текст без маркера →
        одноразовая форс-доставка канона (владелец разрешил перезапись),
        после чего `canon_drift` False — доказательство для гейта T-1641."""
        manual = "<h1>Дрейфованный прод</h1>"
        cache, conn = _cache(_settings_row(manual), monkeypatch)
        with caplog.at_level(logging.WARNING):
            await cache.init()
        value = cache.get(INFO_KEY)
        assert value["html"] == DEFAULT_INFO_TEXT
        assert value["canon_version"] == INFO_CANON_VERSION
        assert value["canon_delivered_version"] == INFO_CANON_VERSION
        assert canon_drift(value["html"]) is False
        assert len(_info_inserts(conn)) == 1
        assert "force-delivered" in caplog.text

    @pytest.mark.asyncio
    async def test_manual_edit_after_delivery_not_overwritten(self, monkeypatch,
                                                              caplog):
        """§8#5 + ревью-итер.1: после доставки (маркер стоит) ручная правка
        НЕ затирается — WARNING + `canon_drift`, reset только явный."""
        manual = "<h1>Моя ручная справка</h1>"
        rows = _settings_row(manual, canon_version=INFO_CANON_VERSION,
                             delivered=INFO_CANON_VERSION)
        cache, conn = _cache(rows, monkeypatch)
        with caplog.at_level(logging.WARNING):
            await cache.init()
        assert cache.get(INFO_KEY)["html"] == manual
        assert _info_inserts(conn) == []
        assert any("drift" in r.message and "изменён вручную" in r.message
                   for r in caplog.records)
        assert canon_drift(manual) is True

    @pytest.mark.asyncio
    async def test_missing_key_is_noop(self, monkeypatch):
        cache, conn = _cache([], monkeypatch)
        await cache._migrate_info_how_it_works_v1015()
        assert _info_inserts(conn) == []

    @pytest.mark.asyncio
    async def test_empty_html_is_noop(self, monkeypatch):
        cache, conn = _cache(_settings_row("   "), monkeypatch)
        await cache._migrate_info_how_it_works_v1015()
        assert _info_inserts(conn) == []

    @pytest.mark.asyncio
    async def test_seed_sets_canon_version(self, monkeypatch, tmp_path):
        """Сид из info_text.md (ключа нет) проставляет canon_version."""
        seed = tmp_path / "seed.md"
        seed.write_text(DEFAULT_INFO_TEXT, encoding="utf-8")
        cache, conn = _cache([], monkeypatch, info_file=str(seed))
        await cache.init()
        value = cache.get(INFO_KEY)
        assert value is not None
        assert value["canon_version"] == INFO_CANON_VERSION
        inserts = _info_inserts(conn)
        assert len(inserts) == 1
