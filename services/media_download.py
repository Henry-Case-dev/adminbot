"""Bugfix 04.09.2026 (Часть 1, FR-4) — общее скачивание TG-медиа в tmp.

Перенос из handlers/voice_transcription.py (_fetch_media_to_tmp, Epic 78,
D292/Section 79) БЕЗ изменения поведения: голосовые (voice_transcription),
кружочки и нативные видео (youtube.py Часть 1), «скачай»-нативные медиа
(handlers/video_download.py Часть 1b) ходят через один хелпер.

Гейт локального режима = hot.get("flags.download_enabled",
settings.DOWNLOAD_ENABLED) (D262 import-time сессия с is_local=True).
Локальный режим И относительный file_path → копирование с диска из
TELEGRAM_API_FILES_DIR/<bot_id>:<token>/; файла нет / get_file упал / path
абсолютный / облако → bot.download (облачный режим байт-в-байт, без
get_file-двойного запроса). Секреты (R17): строка '<bot_id>:<token>'
нигде не логируется.
"""
import asyncio
import logging
import shutil
from pathlib import Path, PurePosixPath

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)


def local_files_subdir(bot) -> str:
    """Epic 78 hotfix: имя каталога data-dir локального Bot API.

    Prod-факт (2026-08-26): telegram-bot-api создаёт каталог с именем,
    равным ПОЛНОМУ токену '<bot_id>:<secret>' — то есть ровно
    settings.API_TOKEN. Продолжаем поддерживать и «голый» secret без
    префикса на всякий случай (старые инсталляции/тестовые стенды).
    Секрет нигде не логируется (R17).
    """
    token = str(settings.API_TOKEN)
    prefix = f"{bot.id}:"
    if token.startswith(prefix):
        return token
    return prefix + token


async def fetch_media_to_tmp(bot, media, tmp_path) -> None:
    """Epic 78 (D292/Section 79): получить медиа во tmp-файл.
    Гейт локального режима = hot.get("flags.download_enabled", settings.DOWNLOAD_ENABLED) (D262 import-time
    сессия с is_local=True). Локальный режим И относительный file_path →
    копирование с диска из TELEGRAM_API_FILES_DIR/<bot_id>:<token>/
    (root cause: локальный Bot API возвращает file_path ОТНОСИТЕЛЬНЫМ,
    aiogram читает исходник относительно cwd → FileNotFoundError).
    Файла нет / get_file упал / path абсолютный / облако → прежний
    bot.download (облачный режим байт-в-байт, без get_file-двойного запроса).
    Секреты (R17): строка '<bot_id>:<token>' нигде не логируется — в логах
    только file_path-хвост или src.name."""
    if not hot.get("flags.download_enabled", settings.DOWNLOAD_ENABLED):            # облачный режим: как раньше
        await bot.download(media.file_id, destination=tmp_path)
        return
    # Epic 78 (D292): локальный Bot API возвращает относительный file_path,
    # файл лежит на диске в TELEGRAM_API_FILES_DIR/<bot_id>:<token>/.
    # Epic 79 hotfix (aiogram 3.31+ race): get_file может вернуть file_path
    # ДО того, как локальный API закеширует файл на диск — src.exists() False,
    # а bot.download() в is_local=True падает FileNotFoundError.
    # Исправление: retry с задержкой (локальный API успевает за ~1-2с), после
    # чего — bot.download (fallback для облачного режима).
    # R17: строка '<bot_id>:<token>' нигде не логируется.
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        file_path = None
        try:
            tg_file = await bot.get_file(media.file_id)
            file_path = getattr(tg_file, "file_path", None)
        except Exception as exc:
            logger.warning("[transcribe] get_file failed (attempt %d/%d) | "
                           "file_id=%s | %s", attempt, max_attempts,
                           media.file_id, type(exc).__name__)
        if (isinstance(file_path, str) and file_path
                and not PurePosixPath(file_path).is_absolute()):
            src = (Path(settings.TELEGRAM_API_FILES_DIR)
                   / local_files_subdir(bot) / file_path)
            try:
                if src.resolve().is_relative_to(
                        Path(settings.TELEGRAM_API_FILES_DIR).resolve()):
                    if src.exists():
                        await asyncio.to_thread(
                            shutil.copyfile, src, tmp_path)
                        return
                    logger.warning(
                        "[transcribe] local api file missing (attempt %d/%d)"
                        " | path=%s", attempt, max_attempts, file_path)
            except OSError as exc:
                # R17: только имя файла и тип ошибки — сообщение OSError
                # содержит ПОЛНЫЙ путь (<bot_id>:<token>), exc_info нельзя.
                logger.warning("[transcribe] host copy failed | file=%s | %s",
                               src.name, type(exc).__name__)
        if attempt < max_attempts:
            await asyncio.sleep(1.0)
    # Все retry исчерпаны. Последняя попытка: bot.download.
    # В локальном режиме (is_local=True) падает FileNotFoundError, если файл
    # всё ещё не на диске — но попытка лучше, чем молчание + 0 ответ.
    logger.warning("[transcribe] local file unavailable after %d attempts | "
                   "file_id=%s | falling back to bot.download",
                   max_attempts, media.file_id)
    await bot.download(media.file_id, destination=tmp_path)
