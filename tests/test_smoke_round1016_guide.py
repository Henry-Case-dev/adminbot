"""Смоук раунда 10.16 (T-1645) — guide «имитация реальной работы».

In-process, без сети: fake-PG ConfigCache (как в проде init), реальные
`InfoService` и хендлеры `/info`/`/edit_info`, мок-бот.
  * прод-PG со старым каноном → `ConfigCache.init()` → новый канон + версия;
  * `/info` отдаёт канон (rich-путь);
  * `/edit_info` (админ) → превью + PG-only запись, файл-сид не пишется;
  * `/edit_info` (не админ) → отказ, без записи;
  * `reset_canon` бэкапит предыдущий текст.
"""
import logging
import types

import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers import info as info_mod
from services import hot_config as hot
from services.config_cache import ConfigCache
from services.info_service import (
    DEFAULT_INFO_TEXT,
    INFO_CANON_VERSION,
    INFO_KEY,
    PREV_DEFAULT_INFO_TEXT,
    InfoService,
    canon_drift,
)

ADMIN_ID = 5885953495
CHAT_ID = -1001234567890


@pytest.fixture(autouse=True)
def _isolate_hot_cache():
    """Не утекать внедрённым ConfigCache в другие тесты (hot — глобал)."""
    prev = hot.get_config_cache()
    yield
    hot.set_config_cache(prev)


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


def _cache(rows, monkeypatch):
    monkeypatch.setattr(
        "services.config_cache.settings",
        types.SimpleNamespace(ADMIN_USER_ID=ADMIN_ID,
                              INFO_TEXT_FILE="no_such_file_1016.md"))
    conn = _FakeConn(rows)
    return ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0), conn


def _msg(text="/info", user_id=ADMIN_ID):
    msg = MagicMock()
    msg.text = text
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.message_id = 55
    msg.delete = AsyncMock()
    return msg


def _bot():
    bot = AsyncMock()
    bot.send_rich_message = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


class TestGuideMigrationSmoke:
    @pytest.mark.asyncio
    async def test_prod_pg_old_text_migrated_to_canon(self, monkeypatch):
        cache, conn = _cache(_settings_row(PREV_DEFAULT_INFO_TEXT), monkeypatch)
        await cache.init()
        value = cache.get(INFO_KEY)
        assert value["html"] == DEFAULT_INFO_TEXT
        assert value["canon_version"] == INFO_CANON_VERSION
        inserts = [q for q in conn.queries if "INSERT INTO bot_settings" in q[0]
                   and q[1] and q[1][0] == INFO_KEY]
        assert len(inserts) == 1

    @pytest.mark.asyncio
    async def test_unknown_prod_text_force_delivered_once(self, monkeypatch,
                                                          caplog):
        """Ревью-итер.1 (High F2): неизвестный прод-текст (не слепок) при
        отсутствии маркера доставки → одноразовая форс-доставка канона;
        `canon_drift` становится False (доказательство для гейта T-1641)."""
        manual = "<h1>Моя ручная справка</h1>"
        cache, _ = _cache(_settings_row(manual), monkeypatch)
        with caplog.at_level(logging.WARNING):
            await cache.init()
        value = cache.get(INFO_KEY)
        assert value["html"] == DEFAULT_INFO_TEXT
        assert value["canon_version"] == INFO_CANON_VERSION
        assert value["canon_delivered_version"] == INFO_CANON_VERSION
        assert canon_drift(value["html"]) is False
        assert "force-delivered" in caplog.text

    @pytest.mark.asyncio
    async def test_force_delivery_backs_up_manual_text(self, monkeypatch):
        """S10.16-2: форс-доставка канона сохраняет прежний ручной текст и его
        updated_at в `prev_html`/`prev_updated_at` (как InfoService.reset_canon)
        — правку можно откатить, а не потерять безвозвратно."""
        manual = "<h1>Моя ручная справка</h1>"
        cache, _ = _cache(_settings_row(manual), monkeypatch)
        await cache.init()
        value = cache.get(INFO_KEY)
        assert value["html"] == DEFAULT_INFO_TEXT
        assert value["canon_delivered_version"] == INFO_CANON_VERSION
        assert value["prev_html"] == manual
        assert value["prev_updated_at"] == "t"

    @pytest.mark.asyncio
    async def test_manual_edit_after_delivery_not_overwritten(self, monkeypatch,
                                                              caplog):
        """После одноразовой доставки (маркер стоит) ручная правка владельца
        НЕ затирается: WARNING + drift, доставка только явным reset."""
        manual = "<h1>Правка после доставки</h1>"
        rows = _settings_row(manual, canon_version=INFO_CANON_VERSION,
                             delivered=INFO_CANON_VERSION)
        cache, _ = _cache(rows, monkeypatch)
        with caplog.at_level(logging.WARNING):
            await cache.init()
        assert cache.get(INFO_KEY)["html"] == manual
        assert "drift" in caplog.text

    @pytest.mark.asyncio
    async def test_idempotent_second_init_no_rewrite(self, monkeypatch):
        """Повторный init с каноном + обоими маркерами → никаких записей."""
        rows = _settings_row(DEFAULT_INFO_TEXT,
                             canon_version=INFO_CANON_VERSION,
                             delivered=INFO_CANON_VERSION)
        cache, conn = _cache(rows, monkeypatch)
        await cache.init()
        inserts = [q for q in conn.queries if "INSERT INTO bot_settings" in q[0]
                   and q[1] and q[1][0] == INFO_KEY]
        assert inserts == []


class TestInfoHandlersSmoke:
    @pytest.fixture
    def env(self, monkeypatch):
        old = info_mod._service
        monkeypatch.setattr(
            info_mod, "settings",
            types.SimpleNamespace(ADMIN_USER_ID=ADMIN_ID,
                                  INFO_COOLDOWN_SECONDS=300))
        bot = _bot()
        yield bot
        info_mod._service = old

    @pytest.mark.asyncio
    async def test_info_sends_canon(self, env, monkeypatch):
        cache, _ = _cache(_settings_row(DEFAULT_INFO_TEXT,
                                        canon_version=INFO_CANON_VERSION),
                          monkeypatch)
        await cache.init()
        hot.set_config_cache(cache)
        service = InfoService(file_path="no_such_file_1016.md")
        service.load()
        info_mod.setup_info(service, db=None)
        monkeypatch.setattr(info_mod, "_cooldown",
                            type(info_mod._cooldown)(0.0))
        await info_mod.cmd_info(_msg(), bot=env)
        env.send_rich_message.assert_awaited()
        sent = env.send_rich_message.await_args.args[1]
        assert sent.html == DEFAULT_INFO_TEXT

    @pytest.mark.asyncio
    async def test_edit_info_non_admin_denied(self, env, monkeypatch):
        monkeypatch.setattr(info_mod.settings, "ADMIN_USER_ID", 999,
                            raising=False)
        service = InfoService(file_path="no_such_file_1016.md")
        service.load()
        info_mod.setup_info(service, db=None)
        await info_mod.cmd_edit_info(_msg("/edit_info новый текст", user_id=1),
                                     bot=env)
        env.send_rich_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_edit_info_admin_saves_pg_only(self, env, monkeypatch):
        cache, _ = _cache(_settings_row(PREV_DEFAULT_INFO_TEXT), monkeypatch)
        await cache.init()
        hot.set_config_cache(cache)
        service = InfoService(file_path="no_such_file_1016.md")
        service.load()
        info_mod.setup_info(service, db=None)
        await info_mod.cmd_edit_info(
            _msg("/edit_info <h1>правка админа</h1>"), bot=env)
        env.send_rich_message.assert_awaited()      # превью в DM
        assert cache.get(INFO_KEY)["html"] == "<h1>правка админа</h1>"


class TestResetCanonSmoke:
    @pytest.mark.asyncio
    async def test_reset_backs_up_previous(self, monkeypatch):
        # Маркер доставки стоит → init НЕ форс-доставляет, ручной текст жив.
        rows = _settings_row("<h1>старый ручной</h1>",
                             canon_version=INFO_CANON_VERSION,
                             delivered=INFO_CANON_VERSION)
        cache, _ = _cache(rows, monkeypatch)
        await cache.init()
        hot.set_config_cache(cache)
        service = InfoService(file_path="no_such_file_1016.md")
        service.load()
        value = await service.reset_canon(updated_by=ADMIN_ID, cache=cache)
        assert value["html"] == DEFAULT_INFO_TEXT
        assert value["prev_html"] == "<h1>старый ручной</h1>"
