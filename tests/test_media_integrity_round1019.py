"""F6 (10.19, ADR-1019-5) — локальный fallback медиа/аватаров + диагностика
рассинхрона ФС↔БД (media_integrity) + R17-чистота.

D-4 (ревью Батча E): honest-контракт `audit_media_files` — `db_media_rows`
(достоверно) и `text_media_paths`/missing/orphan (эвристика по тексту,
`reliable=false`). `restore_missing_files` удалён из публичного API (не имел
call-site и реального path→file_id маппинга) — перенесён в backlog.

Покрытие spec §6:
  * `local_file_path` — относительный под корнем → Path; абсолютный/`../` → None
    (traversal-guard);
  * `read_local_file_bytes` — файл есть (байты), нет (None, 3 попытки);
  * `audit_media_files` — honest-счётчики, R17 (в результате нет
    '<bot_id>:<token>');
  * `_scan_disk` — обход ФС выполняется вне event loop (D-3).
"""
import asyncio
import dataclasses
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from config.settings import settings as real_settings
from services import media_download as md
from services import media_integrity as mi
from services.database import DatabaseService

BOT_ID = 4242
SECRET = f"{BOT_ID}:vt-secret-round1019"
# Windows не допускает ':' в именах каталогов → в тестах подменяем имя
# каталога локального Bot API на безопасное (сам контракт '<bot_id>:<token>'
# проверяется в tests/test_media_download.py).
SUBDIR = "bot-files"


def _cfg(**overrides):
    return dataclasses.replace(real_settings, **overrides)


@pytest.fixture(autouse=True)
def _fast_retry_pause(monkeypatch):
    real_sleep = asyncio.sleep

    async def _sleep(delay):
        if delay < 1.0:
            await real_sleep(delay)

    monkeypatch.setattr(asyncio, "sleep", _sleep)


@pytest.fixture
def media_cfg(tmp_path, monkeypatch):
    """Локальный режим: TELEGRAM_API_FILES_DIR в tmp, реальный API_TOKEN."""
    root = tmp_path / "tgapi"
    cfg = _cfg(DOWNLOAD_ENABLED=True,
               TELEGRAM_API_FILES_DIR=str(root),
               API_TOKEN=SECRET)
    monkeypatch.setattr(md, "settings", cfg)
    monkeypatch.setattr(mi, "settings", cfg)
    monkeypatch.setattr(md, "local_files_subdir", lambda bot: SUBDIR)
    monkeypatch.setattr(mi, "local_files_subdir", lambda bot: SUBDIR)
    return root


def _bot():
    bot = AsyncMock()
    bot.id = BOT_ID
    return bot


def _src_path(root: Path, rel: str) -> Path:
    return root / SUBDIR / rel


class _TgFile:
    def __init__(self, file_path):
        self.file_path = file_path


class TestLocalFileHelpers:
    def test_local_file_path_relative_under_root(self, media_cfg):
        src = md.local_file_path(_bot(), "photos/file_1.jpg")
        assert src == _src_path(media_cfg, "photos/file_1.jpg")

    def test_local_file_path_absolute_none(self, media_cfg):
        assert md.local_file_path(_bot(), "/var/lib/tg/file.jpg") is None

    def test_local_file_path_traversal_none(self, media_cfg):
        assert md.local_file_path(_bot(), "../../secret/keys.bin") is None

    def test_local_file_path_empty_none(self, media_cfg):
        assert md.local_file_path(_bot(), "") is None
        assert md.local_file_path(_bot(), None) is None

    @pytest.mark.asyncio
    async def test_read_local_file_bytes_found(self, media_cfg):
        target = _src_path(media_cfg, "photos/file_1.jpg")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"avatar-bytes")
        bot = _bot()
        bot.get_file.return_value = _TgFile("photos/file_1.jpg")
        assert await md.read_local_file_bytes(bot, "fid") == b"avatar-bytes"

    @pytest.mark.asyncio
    async def test_read_local_file_bytes_missing_three_attempts(
            self, media_cfg):
        bot = _bot()
        bot.get_file.return_value = _TgFile("photos/gone.jpg")
        assert await md.read_local_file_bytes(bot, "fid") is None
        assert bot.get_file.await_count == 3

    @pytest.mark.asyncio
    async def test_read_local_file_bytes_absolute_none(self, media_cfg):
        bot = _bot()
        bot.get_file.return_value = _TgFile("/abs/file.jpg")
        assert await md.read_local_file_bytes(bot, "fid") is None


async def _make_db(tmp_path, name="media.db"):
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


class TestAuditMediaFiles:
    @pytest.mark.asyncio
    async def test_missing_and_orphan_counters(self, media_cfg, tmp_path):
        loc = _src_path(media_cfg, "photos/file_999.jpg")
        loc.parent.mkdir(parents=True, exist_ok=True)
        loc.write_bytes(b"orphan")
        db = await _make_db(tmp_path)
        try:
            await db.db.execute(
                "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
                "media_type) VALUES (1, -100, ?, 100, 'text')",
                ("вот файл photos/file_456.jpg тут",))
            await db.db.execute(
                "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
                "media_type) VALUES (1, -100, 'photo', 101, 'photo')")
            await db.db.commit()
            out = await mi.audit_media_files(db, _bot(), chat_id=-100)
        finally:
            await db.close()
        assert out["db_media_rows"] == 1
        assert out["text_media_paths"] == 1
        assert out["files_on_disk"] == 1
        assert out["missing_on_disk"] == 1
        assert out["orphan_files"] == 1
        assert out["sample_missing"] == ["photos/file_456.jpg"]
        # D-4: honest-контракт — числа из текста, не точный рассинхрон.
        assert out["reliable"] is False
        assert out["basis"] == "text_scan"

    @pytest.mark.asyncio
    async def test_r17_token_absent(self, media_cfg, tmp_path):
        db = await _make_db(tmp_path, "r17.db")
        try:
            await db.db.execute(
                "INSERT INTO smart_messages (user_id, chat_id, text, timestamp) "
                "VALUES (1, -100, 'photos/file_777.jpg', 1)")
            await db.db.commit()
            out = await mi.audit_media_files(db, _bot())
        finally:
            await db.close()
        blob = str(out)
        assert SECRET not in blob
        assert str(media_cfg) not in blob

    @pytest.mark.asyncio
    async def test_fail_open_no_bot(self, media_cfg, tmp_path):
        db = await _make_db(tmp_path, "nobot.db")
        try:
            out = await mi.audit_media_files(db, None)
        finally:
            await db.close()
        assert out["files_on_disk"] == 0
        assert out["missing_on_disk"] == 0

    @pytest.mark.asyncio
    async def test_restore_missing_files_removed_from_public_api(self):
        """Low (ревью Батча E): функция без call-site/восстановления удалена
        из публичного API (backlog)."""
        assert not hasattr(mi, "restore_missing_files")


class TestScanDiskOffEventLoop:
    """D-3/D-2.3 (Medium, ревью итерации 4): тяжёлый обход ФС — в потоке."""

    @pytest.mark.asyncio
    async def test_scan_disk_runs_via_asyncio_to_thread(self, media_cfg,
                                                        tmp_path, monkeypatch):
        real_asyncio = mi.asyncio
        calls: list = []

        class _FakeAsyncio:
            @staticmethod
            async def to_thread(fn, *a, **k):
                calls.append(fn)
                return await real_asyncio.to_thread(fn, *a, **k)

        monkeypatch.setattr(mi, "asyncio", _FakeAsyncio)
        db = await _make_db(tmp_path, "thread.db")
        try:
            out = await mi.audit_media_files(db, _bot())
        finally:
            await db.close()
        assert mi._scan_disk in calls
        assert out["reliable"] is False


class TestMediaHealthEndpoint:
    """D-2.3 (Medium): эндпоинт `/api/status/media-health` на РЕАЛЬНОМ аудите
    (состав полей + honest-контракт + R17-чистота)."""

    @pytest.mark.asyncio
    async def test_endpoint_real_audit_fields_reliable_r17(
            self, media_cfg, tmp_path, monkeypatch):
        from services import lore_runtime, web_runtime
        from web.api import routes
        db = await _make_db(tmp_path, "endpoint.db")
        try:
            await db.db.execute(
                "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
                "media_type) VALUES (1, -100, 'вот photos/file_456.jpg', 1, "
                "'photo')")
            await db.db.commit()
            routes._media_health_cache.clear()
            monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: db)
            monkeypatch.setattr(web_runtime, "get_web_bot", _bot)
            out = await routes.get_status_media_health(
                request=object(), user=object(), x_chat_id=None)
        finally:
            await db.close()
        assert out["available"] is True
        assert out["reliable"] is False
        assert out["basis"] == "text_scan"
        for key in ("db_media_rows", "text_media_paths", "files_on_disk",
                    "missing_on_disk", "orphan_files", "sample_missing"):
            assert key in out
        blob = str(out)
        assert SECRET not in blob
        assert str(media_cfg) not in blob
