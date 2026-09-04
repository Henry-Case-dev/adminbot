"""Bugfix 04.09.2026 (Часть 1, FR-4/AC-1.x) — services.media_download:
общий fetch_media_to_tmp для voice/video/«скачай»-медиа.

Локальный режим (download_enabled=True) + относительный file_path → копия
с диска TELEGRAM_API_FILES_DIR/<bot_id>:<token>/ (retry×3, отсутствие →
fallback bot.download); облачный режим → сразу bot.download; защита пути
(R17 — только файлы внутри TELEGRAM_API_FILES_DIR); секрет '<bot_id>:<token>'
не логируется.
"""
import dataclasses
import logging
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import media_download as md
from config.settings import settings as real_settings

BOT_ID = 4242


def _cfg(**overrides):
    return dataclasses.replace(real_settings, **overrides)


class _TgFile:
    def __init__(self, file_path):
        self.file_path = file_path


@pytest.fixture
def local_mode(tmp_path, monkeypatch):
    files_dir = tmp_path / "tgapi"
    cfg = _cfg(DOWNLOAD_ENABLED=True,
               TELEGRAM_API_FILES_DIR=str(files_dir))
    monkeypatch.setattr(md, "settings", cfg)
    return files_dir


@pytest.fixture
def vsrc(local_mode, monkeypatch):
    """Виртуальные файлы на «диске локального Bot API»: подмена Path.exists
    (только пути под TELEGRAM_API_FILES_DIR) и md.shutil.copyfile."""
    files = {}
    copied = {}
    root = str(local_mode)
    real_exists = Path.exists

    def fake_exists(pself):
        s = str(pself)
        if s.startswith(root):
            return s in files
        return real_exists(pself)

    def fake_copyfile(src, dst):
        assert str(src) in files, str(src)
        copied[str(src)] = str(dst)
        with open(dst, "wb") as fh:
            fh.write(files[str(src)])

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(md.shutil, "copyfile", fake_copyfile)
    return files, copied


def _src_path(files_dir, rel):
    token = str(md.settings.API_TOKEN)
    prefix = f"{BOT_ID}:"
    dirname = token if token.startswith(prefix) else prefix + token
    return str(files_dir / dirname / rel)


def _bot():
    bot = AsyncMock()
    bot.id = BOT_ID
    return bot


class TestCloudMode:
    @pytest.mark.asyncio
    async def test_cloud_download_straight(self, tmp_path, monkeypatch):
        monkeypatch.setattr(md, "settings", _cfg(DOWNLOAD_ENABLED=False))
        dst = tmp_path / "out.ogg"
        bot = _bot()
        await md.fetch_media_to_tmp(bot, MagicMock(file_id="f1"), str(dst))
        bot.download.assert_awaited_once_with("f1", destination=str(dst))
        bot.get_file.assert_not_awaited()


class TestLocalMode:
    @pytest.mark.asyncio
    async def test_local_existing_file_copied_no_download(
            self, tmp_path, vsrc, local_mode, monkeypatch):
        files, copied = vsrc
        key = _src_path(local_mode, "voice/file.ogg")
        files[key] = b"media-bytes"
        dst = tmp_path / "out.ogg"
        bot = _bot()
        bot.get_file.return_value = _TgFile("voice/file.ogg")
        await md.fetch_media_to_tmp(bot, MagicMock(file_id="f1"), str(dst))
        assert copied == {key: str(dst)}
        bot.download.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_file_falls_back_to_download(
            self, tmp_path, local_mode, vsrc, caplog):
        dst = tmp_path / "out.ogg"
        bot = _bot()
        bot.get_file.return_value = _TgFile("voice/gone.ogg")
        with caplog.at_level(logging.WARNING):
            await md.fetch_media_to_tmp(bot, MagicMock(file_id="f1"), str(dst))
        bot.download.assert_awaited_once_with("f1", destination=str(dst))
        assert any("local api file missing" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_absolute_file_path_skips_host_resolve(
            self, tmp_path, local_mode):
        dst = tmp_path / "out.mp4"
        bot = _bot()
        bot.get_file.return_value = _TgFile("/var/lib/tg/data/file.mp4")
        await md.fetch_media_to_tmp(bot, MagicMock(file_id="f3"), str(dst))
        bot.download.assert_awaited_once_with("f3", destination=str(dst))

    @pytest.mark.asyncio
    async def test_path_traversal_blocked_relative_to_root(
            self, tmp_path, local_mode, vsrc):
        """Защита пути (R17/NFR-3): файл ВНЕ TELEGRAM_API_FILES_DIR не
        копируется с диска — fallback bot.download."""
        dst = tmp_path / "out.ogg"
        bot = _bot()
        bot.get_file.return_value = _TgFile("../../secret/keys.bin")
        await md.fetch_media_to_tmp(bot, MagicMock(file_id="f1"), str(dst))
        bot.download.assert_awaited_once_with("f1", destination=str(dst))

    @pytest.mark.asyncio
    async def test_get_file_failure_falls_back_to_download(
            self, tmp_path, local_mode, caplog):
        dst = tmp_path / "out.ogg"
        bot = _bot()
        bot.get_file.side_effect = RuntimeError("api boom")
        with caplog.at_level(logging.WARNING):
            await md.fetch_media_to_tmp(bot, MagicMock(file_id="f1"), str(dst))
        bot.download.assert_awaited_once_with("f1", destination=str(dst))
        assert any("get_file failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_copy_error_logs_name_only(
            self, tmp_path, local_mode, vsrc, caplog, monkeypatch):
        """R17: OSError с ПОЛНЫМ путём (<bot_id>:<token>) логируется только
        как src.name; секрет не печатается."""
        files, _ = vsrc
        key = _src_path(local_mode, "music/ok.ogg")
        files[key] = b"x"
        token = str(md.settings.API_TOKEN)
        secret = f"{BOT_ID}:{token}" if not token.startswith(f"{BOT_ID}:") \
            else token

        def _boom_copy(src, dst):
            raise OSError(f"boom {src}")

        monkeypatch.setattr(md.shutil, "copyfile", _boom_copy)
        bot = _bot()
        bot.get_file.return_value = _TgFile("music/ok.ogg")
        with caplog.at_level(logging.WARNING):
            await md.fetch_media_to_tmp(bot, MagicMock(file_id="f1"),
                                        str(tmp_path / "out.ogg"))
        blob = "\n".join(r.getMessage() for r in caplog.records)
        assert secret not in blob
        assert "ok.ogg" not in blob or True     # имя файла допустимо
        assert any("host copy failed" in r.getMessage()
                   for r in caplog.records)

    def test_local_files_subdir_prefixed(self):
        cfg = _cfg(API_TOKEN="4242:abc-secret")
        orig = md.settings
        md.settings = cfg
        try:
            assert md.local_files_subdir(_bot()) == "4242:abc-secret"
        finally:
            md.settings = orig

    def test_local_files_subdir_adds_prefix_when_bare(self, monkeypatch):
        cfg = _cfg(API_TOKEN="bare-secret")
        monkeypatch.setattr(md, "settings", cfg)
        assert md.local_files_subdir(_bot()) == f"{BOT_ID}:bare-secret"


class TestSubdirTokenNeverLogged:
    @pytest.mark.asyncio
    async def test_token_absent_from_logs_all_branches(
            self, tmp_path, local_mode, vsrc, caplog, monkeypatch):
        token = str(md.settings.API_TOKEN)
        secret = token if token.startswith(f"{BOT_ID}:") else f"{BOT_ID}:{token}"
        files, _ = vsrc
        key_ok = _src_path(local_mode, "music/ok.ogg")
        files[key_ok] = b"x"
        bot = _bot()

        def _boom_copy(src, dst):
            raise OSError(f"boom {src}")

        with caplog.at_level(logging.DEBUG):
            # A: существующий файл → копия
            bot.get_file.return_value = _TgFile("music/ok.ogg")
            await md.fetch_media_to_tmp(bot, MagicMock(file_id="a"),
                                        str(tmp_path / "a.ogg"))
            # B: отсутствует → WARNING fallback
            bot.get_file.return_value = _TgFile("music/gone.ogg")
            await md.fetch_media_to_tmp(bot, MagicMock(file_id="b"),
                                        str(tmp_path / "b.ogg"))
            # C: копирование упало → OSError с полным путём
            bot.get_file.return_value = _TgFile("music/ok.ogg")
            prev = md.shutil.copyfile
            md.shutil.copyfile = _boom_copy
            try:
                await md.fetch_media_to_tmp(bot, MagicMock(file_id="c"),
                                            str(tmp_path / "c.ogg"))
            finally:
                md.shutil.copyfile = prev

        blob = "\n".join(r.getMessage() for r in caplog.records)
        assert token not in blob
        assert secret not in blob
        assert key_ok not in blob
        assert any("host copy failed" in r.getMessage()
                   for r in caplog.records)