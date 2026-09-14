"""F7 `guide-rewrite-persona-round1015` — «Гайд по фичам» под реестр F6 + Имя.

Покрытие (spec §7):
  * канон ``DEFAULT_INFO_TEXT``: правило обязательного обращения, примеры
    «Бот, …»/«Олег, …», rich-HTML-акценты команд;
  * ``чекап``/``фактчек`` описаны как исключения («одним словом, без обращения»);
  * §«Прямое обращение»: отключение дефолтных бот-триггеров при заданном имени;
    снятый алиас «живой собака» отсутствует;
  * идемпотентная DML-миграция ``_migrate_info_how_it_works_v1015``
    (слепок PREV → новый канон; ручные правки неприкосновенны; повтор — no-op).
"""
import logging
import types

import pytest

from services.config_cache import ConfigCache
from services.info_service import (
    DEFAULT_INFO_TEXT,
    PREV_DEFAULT_INFO_TEXT,
)

INFO_KEY = "content.info_how_it_works"
ADMIN_ID = 5885953495


# ── фейки PG (минимальные, только bot_settings) ─────────────────────────────

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


def _settings_row(html, delivered=None):
    value = {"html": html, "updated_at": "t", "updated_by": 1}
    if delivered is not None:
        value["canon_version"] = delivered
        value["canon_delivered_version"] = delivered
    return [{
        "key": INFO_KEY,
        "value": value,
        "category": "content",
    }]


def _cache(html, monkeypatch, delivered=None):
    monkeypatch.setattr(
        "services.config_cache.settings",
        types.SimpleNamespace(ADMIN_USER_ID=ADMIN_ID))
    conn = _FakeConn(_settings_row(html, delivered))
    return ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0), conn


def _info_inserts(conn):
    """INSERT-ы в bot_settings именно по ключу info_how_it_works."""
    return [q for q in conn.queries
            if "INSERT INTO bot_settings" in q[0]
            and q[1] and q[1][0] == INFO_KEY]


# ── содержание канона ───────────────────────────────────────────────────────

class TestCanonContent:
    def test_appeal_rule_explicit(self):
        assert "требуют обращения" in DEFAULT_INFO_TEXT
        for cmd in ("Бот, загугли", "Олег, загугли",
                    "Бот, скачай", "Олег, скачай"):
            assert cmd in DEFAULT_INFO_TEXT, cmd

    def test_bare_exceptions(self):
        assert "чекап" in DEFAULT_INFO_TEXT
        assert "фактчек" in DEFAULT_INFO_TEXT
        assert "одним словом, без обращения" in DEFAULT_INFO_TEXT

    def test_name_rule_disables_default_triggers(self):
        assert "Прямое обращение" in DEFAULT_INFO_TEXT
        assert "больше не будят" in DEFAULT_INFO_TEXT
        assert "свое имя" in DEFAULT_INFO_TEXT
        assert "живой собака" not in DEFAULT_INFO_TEXT

    def test_retired_aliases_absent(self):
        for stale in ("пульс бота", "как сервак", "перескажи видос",
                      "ботохуета"):
            assert stale not in DEFAULT_INFO_TEXT, stale

    def test_commands_highlighted_and_new_canon(self):
        assert DEFAULT_INFO_TEXT.count("<h4><b><i>") == 34
        assert DEFAULT_INFO_TEXT != PREV_DEFAULT_INFO_TEXT


# ── идемпотентная доставка в PG ─────────────────────────────────────────────

class TestInfoMigration:
    @pytest.mark.asyncio
    async def test_prev_canon_replaced_by_new(self, monkeypatch):
        cache, conn = _cache(PREV_DEFAULT_INFO_TEXT, monkeypatch)
        await cache.init()
        value = cache.get(INFO_KEY)
        assert value["html"] == DEFAULT_INFO_TEXT
        assert value["updated_by"] == ADMIN_ID
        assert value["updated_at"]
        assert len(_info_inserts(conn)) == 1

    @pytest.mark.asyncio
    async def test_unknown_text_force_delivered_once(self, monkeypatch, caplog):
        """Ревью-итер.1 (High F2): неизвестный текст БЕЗ маркера доставки →
        одноразовая форс-доставка канона (владелец разрешил перезапись)."""
        manual = "<h1>Моя ручная справка</h1>"
        cache, conn = _cache(manual, monkeypatch)
        with caplog.at_level(logging.WARNING):
            await cache.init()
        assert cache.get(INFO_KEY)["html"] == DEFAULT_INFO_TEXT
        assert len(_info_inserts(conn)) == 1
        assert "force-delivered" in caplog.text

    @pytest.mark.asyncio
    async def test_manual_edit_not_overwritten(self, monkeypatch, caplog):
        """После доставки (маркер стоит) ручная правка НЕ затирается."""
        manual = "<h1>Моя ручная справка</h1>"
        cache, conn = _cache(manual, monkeypatch, delivered=2)
        with caplog.at_level(logging.WARNING):
            await cache.init()
        assert cache.get(INFO_KEY)["html"] == manual
        assert _info_inserts(conn) == []
        assert any("изменён вручную" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_idempotent_second_run_noop(self, monkeypatch):
        cache, conn = _cache(PREV_DEFAULT_INFO_TEXT, monkeypatch)
        await cache.init()
        inserts_before = len(_info_inserts(conn))
        assert inserts_before == 1
        await cache._migrate_info_how_it_works_v1015()   # повтор → no-op
        assert len(_info_inserts(conn)) == inserts_before
        assert cache.get(INFO_KEY)["html"] == DEFAULT_INFO_TEXT

    @pytest.mark.asyncio
    async def test_missing_key_is_noop(self, monkeypatch):
        monkeypatch.setattr(
            "services.config_cache.settings",
            types.SimpleNamespace(ADMIN_USER_ID=ADMIN_ID))
        conn = _FakeConn([])
        cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
        await cache._migrate_info_how_it_works_v1015()
        assert _info_inserts(conn) == []
