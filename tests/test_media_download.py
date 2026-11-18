"""P0 voice-transcription recovery (18.11.2026) — единый транспорт voice.

`fetch_media_to_tmp` больше не делает 3 одинаковых `bot.get_file` + «fallback»
`bot.download`: это streaming-адаптер того же транспорта, что Vision
(`download_api_file_to_path`): стадии get_file|local_read|cloud_download|
validate и классы MediaDownloadError. Постоянный отказ (invalid_file_id,
permission_denied) — ОДНА попытка и без облака; transient — bounded retry;
облачный fallback — только при разрешённом MEDIA_DOWNLOAD_CLOUD_FALLBACK;
режим endpoint'а — фактическая сессия/`TELEGRAM_LOCAL`, а не функциональный
`flags.download_enabled`.

TEST-LIFECYCLE: CONTRACT owner=VOICE-TRANSCRIPTION-RECOVERY-01 (A/B/D);
TEST-LIFECYCLE: REGRESSION owner=Epic 78 (local API path), R17 (token).
"""
import asyncio
import dataclasses
import logging
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from config.settings import settings as real_settings
from services import media_download as md

BOT_ID = 4242
TOKEN = f"{BOT_ID}:voice-recovery-test-token"


@pytest.fixture(autouse=True)
def _fast_retry_pause(monkeypatch):
    """Паузы 1.0s между bounded retry не нужны тестам логики."""
    real_sleep = asyncio.sleep

    async def _sleep(delay):
        if delay < 1.0:
            await real_sleep(delay)

    monkeypatch.setattr(asyncio, "sleep", _sleep)


def _cfg(**overrides):
    return dataclasses.replace(real_settings, **overrides)


@pytest.fixture(autouse=True)
def _cloud_off(monkeypatch):
    """По умолчанию облако выключено: ни один тест не ходит в сеть."""
    monkeypatch.setenv(md.CLOUD_FALLBACK_ENV, "0")


@pytest.fixture
def no_hot_flag(monkeypatch):
    """Функциональный флаг модуля выключен — endpoint он менять не должен."""
    from services import hot_config as hot
    monkeypatch.setattr(hot, "get", lambda key, default=None: (
        False if key == "flags.download_enabled" else default))


@pytest.fixture
def local_cfg(tmp_path, monkeypatch):
    files_dir = tmp_path / "tgapi"
    cfg = _cfg(TELEGRAM_API_FILES_DIR=str(files_dir), API_TOKEN=TOKEN)
    monkeypatch.setattr(md, "settings", cfg)
    monkeypatch.setenv("TELEGRAM_LOCAL", "1")
    return files_dir


class _Session:
    def __init__(self, is_local: bool):
        self.api = types.SimpleNamespace(is_local=is_local)


class _Bot:
    """Двойник бота с фактической сессией и настоящей записью в destination."""

    def __init__(self, *, local: bool = True, data: bytes = b"audio-bytes",
                 file_path: str = "voice/file.ogg"):
        self.session = _Session(local)
        self.id = BOT_ID
        self.token = TOKEN
        self.data = data
        self.file_path = file_path
        self.get_file_calls = 0
        self.download_file_calls = 0
        self.download_calls = 0
        self.get_file_exc: BaseException | None = None
        self.download_exc: BaseException | None = None

    async def get_file(self, file_id):
        self.get_file_calls += 1
        if self.get_file_exc is not None:
            raise self.get_file_exc
        return types.SimpleNamespace(file_path=self.file_path)

    async def download_file(self, file_path, destination=None, timeout=30):
        self.download_file_calls += 1
        if self.download_exc is not None:
            raise self.download_exc
        if self.data is None:
            raise FileNotFoundError(file_path)
        if isinstance(destination, str):
            Path(destination).write_bytes(self.data)
        else:
            destination.write(self.data)

    async def download(self, file, destination=None):
        self.download_calls += 1
        target = getattr(file, "file_id", file)
        if self.download_exc is not None:
            raise self.download_exc
        if isinstance(destination, str):
            Path(destination).write_bytes(self.data)
        else:
            destination.write(self.data)
        return target


class _BadRequest(Exception):
    """Постоянный 400 Telegram (invalid file identifier)."""


class _Cloud:
    def __init__(self, data: bytes = b"cloud-bytes"):
        self.data = data
        self.calls = []

    async def __call__(self, token, file_id, rel_path, *, timeout,
                       max_bytes):
        self.calls.append({"token": token, "file_id": file_id,
                           "rel": rel_path, "timeout": timeout,
                           "max_bytes": max_bytes})
        return self.data


@pytest.mark.asyncio
async def test_cloud_mode_getfile_then_transport_no_disk(
        tmp_path, monkeypatch, no_hot_flag):
    """Cloud-режим: getFile → download_file; локальный диск не участвует."""
    monkeypatch.setenv("TELEGRAM_LOCAL", "")
    monkeypatch.setattr(md, "settings", _cfg(API_TOKEN=TOKEN))
    bot = _Bot(local=False, data=b"cloud-audio")
    dst = tmp_path / "out.ogg"
    await md.fetch_media_to_tmp(bot, MagicMock(file_id="f1"), str(dst))
    assert bot.get_file_calls == 1
    assert bot.download_file_calls == 1
    assert bot.download_calls == 0
    assert dst.read_bytes() == b"cloud-audio"


@pytest.mark.asyncio
async def test_local_file_copied_without_transport(
        tmp_path, local_cfg, monkeypatch, no_hot_flag):
    """Локальный режим: файл на диске → копия; HTTP-транспорт не зовётся."""
    src = tmp_path / "src.ogg"
    src.write_bytes(b"disk-audio")
    monkeypatch.setattr(md, "local_file_path", lambda bot, fp: src)
    bot = _Bot(local=True)
    dst = tmp_path / "out.ogg"
    await md.fetch_media_to_tmp(bot, MagicMock(file_id="f1"), str(dst))
    assert dst.read_bytes() == b"disk-audio"
    assert bot.download_file_calls == 0
    assert bot.download_calls == 0


@pytest.mark.asyncio
async def test_hot_flag_does_not_select_endpoint(
        tmp_path, local_cfg, monkeypatch, no_hot_flag):
    """flags.download_enabled=False не переключает local-сессию в облако."""
    src = tmp_path / "src.ogg"
    src.write_bytes(b"disk-audio")
    monkeypatch.setattr(md, "local_file_path", lambda bot, fp: src)
    bot = _Bot(local=True)
    dst = tmp_path / "out.ogg"
    await md.fetch_media_to_tmp(bot, MagicMock(file_id="f1"), str(dst))
    assert dst.read_bytes() == b"disk-audio"
    assert bot.get_file_calls == 1
    assert bot.download_file_calls == 0


@pytest.mark.asyncio
async def test_local_400_is_not_invalid_and_uses_cloud(
        tmp_path, local_cfg, monkeypatch):
    """Prod-диагноз 18.11.2026: локальный 400 wrong file_id — НЕ invalid.

    Ровно одна попытка local → typed local_read_failed → облако (200).
    """
    monkeypatch.setenv(md.CLOUD_FALLBACK_ENV, "1")
    cloud = _Cloud(b"cloud-recovered")

    async def _fetch(token, file_id, rel_path, *, timeout, max_bytes):
        return await cloud(token, file_id, rel_path, timeout=timeout,
                           max_bytes=max_bytes)

    bot = _Bot(local=True)
    bot.get_file_exc = _BadRequest(
        "Bad Request: wrong file_id or the file is temporarily unavailable")
    dst = tmp_path / "out.ogg"
    diag: dict = {}
    await md.download_api_file_to_path(
        bot, "f1", str(dst), site="transcribe", cloud_fetcher=_fetch,
        diagnostics=diag)
    assert bot.get_file_calls == 1
    assert cloud.calls and cloud.calls[0]["rel"] == ""
    assert cloud.calls[0]["file_id"] == "f1"
    assert dst.read_bytes() == b"cloud-recovered"
    assert diag["outcome"] == "cloud_fallback"
    assert diag.get("error_class") == md.ERROR_LOCAL_READ_FAILED


@pytest.mark.asyncio
async def test_local_400_without_cloud_is_local_read_failed(
        tmp_path, local_cfg):
    """Без облака локальный 400 — терминальный local_read_failed, 1 попытка."""
    bot = _Bot(local=True)
    bot.get_file_exc = _BadRequest(
        "Bad Request: wrong file_id or the file is temporarily unavailable")
    with pytest.raises(md.MediaDownloadError) as ei:
        await md.fetch_media_to_tmp(bot, MagicMock(file_id="f1"), str(
            tmp_path / "out.ogg"), site="transcribe")
    assert (ei.value.stage, ei.value.error_class) == (
        md.STAGE_GET_FILE, md.ERROR_LOCAL_READ_FAILED)
    assert ei.value.retryable is False
    assert bot.get_file_calls == 1


@pytest.mark.asyncio
async def test_cloud_mode_invalid_file_id_is_terminal(
        tmp_path, monkeypatch):
    """invalid_file_id авторитетно определяет облако: терминально, 1 попытка."""
    monkeypatch.setenv("TELEGRAM_LOCAL", "")
    monkeypatch.setattr(md, "settings", _cfg(API_TOKEN=TOKEN))
    bot = _Bot(local=False)
    bot.get_file_exc = _BadRequest(
        "Bad Request: invalid file identifier specified")
    with pytest.raises(md.MediaDownloadError) as ei:
        await md.fetch_media_to_tmp(bot, MagicMock(file_id="bad"), str(
            tmp_path / "out.ogg"))
    assert (ei.value.stage, ei.value.error_class) == (
        md.STAGE_GET_FILE, md.ERROR_INVALID_FILE_ID)
    assert ei.value.retryable is False
    assert bot.get_file_calls == 1


@pytest.mark.asyncio
async def test_transient_timeout_bounded_retry(
        tmp_path, local_cfg):
    """Timeout/timeout-ish — bounded retry, затем typed timeout."""
    bot = _Bot(local=True)
    bot.get_file_exc = asyncio.TimeoutError()
    with pytest.raises(md.MediaDownloadError) as ei:
        await md.fetch_media_to_tmp(bot, MagicMock(file_id="f1"), str(
            tmp_path / "out.ogg"))
    assert ei.value.stage == md.STAGE_GET_FILE
    assert ei.value.error_class == md.ERROR_TIMEOUT
    assert bot.get_file_calls == 3


@pytest.mark.asyncio
async def test_local_permission_one_attempt_then_cloud_truth(
        tmp_path, local_cfg, monkeypatch):
    """Локальный auth/permission — 1 попытка, облако даёт авторитетный ответ."""
    monkeypatch.setenv(md.CLOUD_FALLBACK_ENV, "1")
    cloud = _Cloud(b"cloud-ok")

    async def _fetch(token, file_id, rel_path, *, timeout, max_bytes):
        return await cloud(token, file_id, rel_path, timeout=timeout,
                           max_bytes=max_bytes)

    bot = _Bot(local=True)
    bot.get_file_exc = PermissionError("Forbidden")
    dst = tmp_path / "out.ogg"
    await md.download_api_file_to_path(bot, "f1", str(dst),
                                       cloud_fetcher=_fetch)
    assert bot.get_file_calls == 1
    assert cloud.calls
    assert dst.read_bytes() == b"cloud-ok"


@pytest.mark.asyncio
async def test_missing_local_file_cloud_fallback(
        tmp_path, local_cfg, monkeypatch):
    """Файла нет на диске и облако разрешено → fallback с относительным путём."""
    monkeypatch.setenv(md.CLOUD_FALLBACK_ENV, "1")
    cloud = _Cloud(b"fallback-audio")
    bot = _Bot(local=True, file_path="voice/gone.ogg")
    dst = tmp_path / "out.ogg"
    diag: dict = {}

    async def _fetch(token, file_id, rel_path, *, timeout, max_bytes):
        return await cloud(token, file_id, rel_path, timeout=timeout,
                           max_bytes=max_bytes)

    # local_file_path не патчим: реального каталога нет → missing_local_file.
    await md.download_api_file_to_path(
        bot, "f1", str(dst), site="transcribe", attempts=2, sleep=0,
        cloud_fetcher=_fetch, diagnostics=diag)
    assert dst.read_bytes() == b"fallback-audio"
    assert cloud.calls and cloud.calls[0]["rel"] == "voice/gone.ogg"
    assert diag["outcome"] == "cloud_fallback"


@pytest.mark.asyncio
async def test_missing_local_file_cloud_disabled_is_typed(
        tmp_path, local_cfg, monkeypatch):
    """Облако запрещено → честный missing_local_file, не «unknown»."""
    monkeypatch.setattr(md, "local_file_path",
                        lambda bot, fp: tmp_path / "gone.ogg")
    bot = _Bot(local=True, file_path="voice/gone.ogg")
    with pytest.raises(md.MediaDownloadError) as ei:
        await md.fetch_media_to_tmp(bot, MagicMock(file_id="f1"), str(
            tmp_path / "out.ogg"))
    assert (ei.value.stage, ei.value.error_class) == (
        md.STAGE_LOCAL_READ, md.ERROR_MISSING_LOCAL_FILE)
    assert ei.value.retryable is True


@pytest.mark.asyncio
async def test_copy_permission_error_typed_without_cloud(
        tmp_path, local_cfg, monkeypatch):
    """Облако выключено: ошибка чтения/копии → typed permission_denied."""
    src = tmp_path / "src.ogg"
    src.write_bytes(b"x")
    monkeypatch.setattr(md, "local_file_path", lambda bot, fp: src)

    def _boom(src_path, dst):
        raise PermissionError("denied")

    monkeypatch.setattr(md.shutil, "copyfile", _boom)
    bot = _Bot(local=True)
    with pytest.raises(md.MediaDownloadError) as ei:
        await md.fetch_media_to_tmp(bot, MagicMock(file_id="f1"), str(
            tmp_path / "out.ogg"))
    assert ei.value.error_class == md.ERROR_PERMISSION_DENIED
    assert bot.get_file_calls == 1


@pytest.mark.asyncio
async def test_local_copy_error_uses_cloud_when_allowed(
        tmp_path, local_cfg, monkeypatch):
    """Ошибка локального чтения — повод для авторитетного облачного ответа."""
    src = tmp_path / "src.ogg"
    src.write_bytes(b"x")
    monkeypatch.setattr(md, "local_file_path", lambda bot, fp: src)
    monkeypatch.setenv(md.CLOUD_FALLBACK_ENV, "1")
    cloud = _Cloud(b"cloud-after-copy-error")

    async def _fetch(token, file_id, rel_path, *, timeout, max_bytes):
        return await cloud(token, file_id, rel_path, timeout=timeout,
                           max_bytes=max_bytes)

    def _boom(src_path, dst):
        raise PermissionError("denied")

    monkeypatch.setattr(md.shutil, "copyfile", _boom)
    bot = _Bot(local=True)
    dst = tmp_path / "out.ogg"
    await md.download_api_file_to_path(bot, "f1", str(dst),
                                       cloud_fetcher=_fetch)
    assert cloud.calls
    assert dst.read_bytes() == b"cloud-after-copy-error"


@pytest.mark.asyncio
async def test_large_file_size_limit_is_oversized(
        tmp_path, local_cfg, monkeypatch):
    """max_bytes: локальный файл больше лимита → typed oversized, без копии."""
    src = tmp_path / "big.ogg"
    src.write_bytes(b"x" * 64)
    monkeypatch.setattr(md, "local_file_path", lambda bot, fp: src)
    dst = tmp_path / "out.ogg"
    with pytest.raises(md.MediaDownloadError) as ei:
        await md.fetch_media_to_tmp(bot=_Bot(local=True),
                                    media=MagicMock(file_id="f1"),
                                    tmp_path=str(dst), max_bytes=16)
    assert ei.value.error_class == md.ERROR_OVERSIZED
    assert ei.value.retryable is False
    assert not dst.exists()


@pytest.mark.asyncio
async def test_container_path_maps_to_host_root(local_cfg):
    """Контейнерный путь `--local` нормализуется к host-корню."""
    bot = types.SimpleNamespace(id=BOT_ID)
    mapped = md.normalize_api_file_path(
        bot, f"/var/lib/telegram-bot-api/{TOKEN}/voice/file.ogg",
        Path(md.settings.TELEGRAM_API_FILES_DIR))
    assert mapped == Path(md.settings.TELEGRAM_API_FILES_DIR) / TOKEN / \
        "voice/file.ogg"


@pytest.mark.asyncio
async def test_token_and_full_file_id_never_logged(
        tmp_path, local_cfg, monkeypatch, caplog):
    """R17: токен и полный file_id не попадают в логи отказа."""
    bot = _Bot(local=True)
    bot.get_file_exc = _BadRequest(
        "Bad Request: invalid file identifier specified")
    full_id = "AgAD" + "x" * 80
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(md.MediaDownloadError):
            await md.fetch_media_to_tmp(
                bot, MagicMock(file_id=full_id), str(tmp_path / "o.ogg"),
                site="transcribe")
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert TOKEN not in blob
    assert "voice-recovery-test-token" not in blob
    assert full_id not in blob
    assert full_id[:6] in blob          # префикс для корреляции — можно


def test_local_files_subdir_prefixed():
    cfg = _cfg(API_TOKEN=TOKEN)
    original = md.settings
    md.settings = cfg
    try:
        assert md.local_files_subdir(_Bot(local=True)) == TOKEN
    finally:
        md.settings = original


def test_local_files_subdir_adds_prefix_when_bare(monkeypatch):
    monkeypatch.setattr(md, "settings", _cfg(API_TOKEN="bare-secret"))
    assert md.local_files_subdir(_Bot(local=True)) == f"{BOT_ID}:bare-secret"
