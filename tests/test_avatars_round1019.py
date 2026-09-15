"""F6 (10.19, ADR-1019-5 D2) — аватары: локальный fallback как media_download.

`fetch_avatar_bytes` при относительном `file_path` локального Bot API читает
файл из `TELEGRAM_API_FILES_DIR/<bot_id:token>/<path>` (через общий хелпер
`read_local_file_bytes`); при отсутствии — прежний `bot.download_file`.
Транзиентные ошибки (`TelegramRetryAfter`/`TelegramNetworkError`) по-прежнему
НЕ кэшируются (BUG-4). R17: секрет '<bot_id>:<token>' не логируется/не
отдаётся.
"""
import dataclasses
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramNetworkError

from config.settings import settings as real_settings
from services import media_download as md
from web.api import avatars

BOT_ID = 4242
SECRET = f"{BOT_ID}:vt-secret-avatars"
SUBDIR = "bot-files"


def _cfg(**overrides):
    return dataclasses.replace(real_settings, **overrides)


@pytest.fixture
def avatar_env(tmp_path, monkeypatch):
    root = tmp_path / "tgapi"
    cfg = _cfg(DOWNLOAD_ENABLED=True, TELEGRAM_API_FILES_DIR=str(root),
               API_TOKEN=SECRET)
    monkeypatch.setattr(md, "settings", cfg)
    monkeypatch.setattr(md, "local_files_subdir", lambda bot: SUBDIR)
    monkeypatch.setattr(avatars.hot, "get", lambda key, default=None: True)
    monkeypatch.setattr(avatars, "_avatar_cache", {})
    return root


class _TgFile:
    def __init__(self, file_path):
        self.file_path = file_path


def _bot():
    bot = AsyncMock()
    bot.id = BOT_ID
    return bot


@pytest.mark.asyncio
async def test_local_fallback_reads_disk(avatar_env, monkeypatch):
    target = avatar_env / SUBDIR / "photos" / "file_1.jpg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"local-avatar")
    bot = _bot()
    bot.get_file.return_value = _TgFile("photos/file_1.jpg")
    monkeypatch.setattr(avatars, "_avatar_file_id",
                        AsyncMock(return_value="fid"))
    monkeypatch.setattr(avatars.web_runtime, "get_web_bot", lambda: bot)
    data = await avatars.fetch_avatar_bytes("user", 525660918)
    assert data == b"local-avatar"
    bot.download_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_local_falls_back_to_download(avatar_env, monkeypatch):
    bot = _bot()
    bot.get_file.return_value = _TgFile("photos/file_456.jpg")

    async def _download(path, destination):
        destination.write(b"cloud-avatar")

    bot.download_file.side_effect = _download
    monkeypatch.setattr(avatars, "_avatar_file_id",
                        AsyncMock(return_value="fid"))
    monkeypatch.setattr(avatars.web_runtime, "get_web_bot", lambda: bot)
    data = await avatars.fetch_avatar_bytes("user", 525660918)
    assert data == b"cloud-avatar"
    bot.download_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_transient_not_cached(avatar_env, monkeypatch):
    bot = _bot()
    bot.get_file.side_effect = TelegramNetworkError(method=None,
                                                   message="net down")
    monkeypatch.setattr(avatars, "_avatar_file_id",
                        AsyncMock(return_value="fid"))
    monkeypatch.setattr(avatars.web_runtime, "get_web_bot", lambda: bot)
    assert await avatars.fetch_avatar_bytes("user", 1) is None
    assert avatars._avatar_cache == {}          # негатив НЕ записан (BUG-4)


@pytest.mark.asyncio
async def test_r17_secret_absent_from_logs(avatar_env, monkeypatch, caplog):
    import logging
    bot = _bot()
    bot.get_file.return_value = _TgFile("photos/gone.jpg")
    monkeypatch.setattr(avatars, "_avatar_file_id",
                        AsyncMock(return_value="fid"))
    monkeypatch.setattr(avatars.web_runtime, "get_web_bot", lambda: bot)
    with caplog.at_level(logging.DEBUG):
        data = await avatars.fetch_avatar_bytes("user", 1)
    assert data is None
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert SECRET not in blob
    assert str(avatar_env) not in blob
    assert "photos/gone.jpg" in blob          # хвост допустим (R17)
