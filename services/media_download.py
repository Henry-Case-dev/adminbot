"""Bugfix 04.09.2026 (Часть 1, FR-4) — общее скачивание TG-медиа в tmp.

Перенос из handlers/voice_transcription.py (_fetch_media_to_tmp, Epic 78,
D292/Section 79) БЕЗ изменения поведения: голосовые (voice_transcription),
кружочки и нативные видео (youtube.py Часть 1), «скачай»-нативные медиа
(handlers/video_download.py Часть 1b) ходят через один хелпер.

Гейт локального режима = hot.get("flags.download_enabled",
settings.DOWNLOAD_ENABLED) (D262 import-time сессия с is_local=True).
Локальный режим И file_path под корнем TELEGRAM_API_FILES_DIR (относительный
→ root/<bot_id:token>/<path>; абсолютный — только если он внутри корня;
контейнерный `/var/lib/telegram-bot-api/…` нормализуется к host-корню) →
копирование с диска; файла нет / get_file упал / path вне корня / облако →
bot.download (облачный режим байт-в-байт, без get_file-двойного запроса).
Секреты (R17): строка '<bot_id>:<token>' нигде не логируется.
"""
import asyncio
import logging
import shutil
from pathlib import Path, PurePosixPath

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

# D263 (ADR-1025-6) / P0 prod-incident (21.09.2026): каталог локального
# Bot API В ПРОСТРАНСТВЕ КОНТЕЙНЕРА. bind-источник тома
# `./docker/telegram-bot-api` (= settings.TELEGRAM_API_FILES_DIR на хосте)
# виден в контейнере как `/var/lib/telegram-bot-api`. Локальный Bot API
# (`--local`) отдаёт АБСОЛЮТНЫЙ контейнерный путь — его префикс
# нормализуется к host-корню (без серверных симлинков).
CONTAINER_API_FILES_ROOT = "/var/lib/telegram-bot-api"


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


def _is_within_root(candidate: Path, root: Path) -> bool:
    """traversal-guard: candidate после resolve() лежит под root (resolve)."""
    try:
        return candidate.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def normalize_api_file_path(bot, file_path: str, root: Path) -> Path | None:
    """P0/ADAPTER: нормализует `file_path` локального Bot API к host-корню.

    * контейнерный абсолютный (`/var/lib/telegram-bot-api/<bot_id>:<token>/…`,
      как отдаёт `--local`) → `root/<bot_id>:<token>/…`;
    * иной абсолютный (host, в т.ч. Windows `C:\\…`) → как есть;
    * относительный → `root/<bot_id:token>/<file_path>`.
    Возвращает путь БЕЗ проверки корня (её делает `_is_within_root`).
    Ровно контейнерный root без хвоста → None (fail-closed).
    R17: '<bot_id>:<token>' наружу не логируется.
    """
    pp = PurePosixPath(file_path)
    if pp.is_absolute():
        s = str(pp)
        if s == CONTAINER_API_FILES_ROOT:
            return None
        if s.startswith(CONTAINER_API_FILES_ROOT + "/"):
            rel = s[len(CONTAINER_API_FILES_ROOT) + 1:]
            return root / rel
        return Path(file_path)
    if Path(file_path).is_absolute():      # Windows-host абсолютный (C:\\…)
        return Path(file_path)
    return root / local_files_subdir(bot) / file_path


def local_file_path(bot, file_path) -> Path | None:
    """Безопасный резолв file_path под корнем TELEGRAM_API_FILES_DIR.

    Локальный Bot API (`--local`) может вернуть ОТНОСИТЕЛЬНЫЙ путь (обычный
    случай: `videos/file_0.mp4` → root/<bot_id:token>/<path>) ЛИБО АБСОЛЮТНЫЙ
    (путь внутри каталога Bot API, в т.ч. контейнерный
    `/var/lib/telegram-bot-api/…` — нормализуется к host-корню, см.
    `normalize_api_file_path`). Итоговый путь принимается ТОЛЬКО если он
    лежит под `TELEGRAM_API_FILES_DIR`; выход за корень / чужая ФС / мусор →
    None → fallback `bot.download` (в облаке — штатный путь). R17:
    возвращаемый Path содержит '<bot_id>:<token>', наружу НЕ логируется.

    D263/ADR-1025-6: `TELEGRAM_API_FILES_DIR` (host) — bind-source тома
    `./docker/telegram-bot-api`, который в контейнере виден как
    `/var/lib/telegram-bot-api`.
    """
    if not isinstance(file_path, str) or not file_path:
        return None
    root = Path(settings.TELEGRAM_API_FILES_DIR)
    candidate = normalize_api_file_path(bot, file_path, root)
    if candidate is None:
        return None
    return candidate if _is_within_root(candidate, root) else None


async def read_host_file_bytes(bot, file_path: str) -> bytes | None:
    """P0: байты файла локального Bot API из host-корня по `file_path`.

    Использует `local_file_path` (нормализация container→host + traversal-
    guard). None — путь вне корня / файла нет / ошибка чтения (вызывающий
    делает свой fallback, напр. `bot.download`/`bot.download_file`). R17:
    путь с '<bot_id>:<token>' не логируется."""
    src = local_file_path(bot, file_path)
    if src is None:
        return None
    try:
        if src.exists():
            return await asyncio.to_thread(src.read_bytes)
    except OSError:
        return None
    return None



async def _read_local_source(bot, file_id, on_found, *, attempts: int = 3,
                             sleep: float = 1.0, site: str = "transcribe") -> bool:
    """Общий retry-цикл локального чтения файла Bot API (F6/ADR-1019-5 D1).

    `on_found(src: Path)` вызывается для существующего файла под корнем;
    True → успех. `get_file` упал / файла нет / траversal / copy-ошибка →
    следующая попытка; после `attempts` — False (вызывающий делает
    собственный fallback). R17: логируются только file_path-хвост/file_id/
    имя файла/тип ошибки (абсолютный путь с '<bot_id>:<token>' — НИКОГДА)."""
    for attempt in range(1, attempts + 1):
        file_path = None
        try:
            tg_file = await bot.get_file(file_id)
            file_path = getattr(tg_file, "file_path", None)
        except Exception as exc:
            logger.warning("[%s] get_file failed (attempt %d/%d) | "
                           "file_id=%s | %s", site, attempt, attempts,
                           file_id, type(exc).__name__)
        src = local_file_path(bot, file_path)
        if src is not None:
            try:
                if src.exists():
                    await on_found(src)
                    return True
                logger.warning(
                    "[%s] local api file missing (attempt %d/%d) | path=%s",
                    site, attempt, attempts, file_path)
            except OSError as exc:
                # R17: только имя файла и тип ошибки — сообщение OSError
                # содержит ПОЛНЫЙ путь (<bot_id>:<token>), exc_info нельзя.
                logger.warning("[%s] host copy failed | file=%s | %s",
                               site, src.name, type(exc).__name__)
        if attempt < attempts:
            await asyncio.sleep(sleep)
    return False


async def read_local_file_bytes(bot, file_id: str, *, attempts: int = 3,
                                sleep: float = 1.0) -> bytes | None:
    """F6 (ADR-1019-5 D1): локальный Bot API — относительный file_path →
    байты из TELEGRAM_API_FILES_DIR/<bot_id:token>/<path>; до `attempts`
    попыток (API кеширует файл с задержкой ~1-2с); None, если файла нет /
    облако / ошибка. Fallback `bot.download` — на вызывающем.
    R17: '<bot_id>:<token>' не логируется — только file_path-хвост/имя."""
    box: dict[str, bytes] = {}

    async def _grab(src: Path) -> None:
        box["data"] = await asyncio.to_thread(src.read_bytes)

    ok = await _read_local_source(bot, file_id, _grab, attempts=attempts,
                                  sleep=sleep, site="media")
    return box.get("data") if ok else None


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
    только file_path-хвост или src.name.

    F6 (ADR-1019-5 D1): локальный retry-цикл вынесен в общий
    `_read_local_source`/`local_file_path` (без дублирования с аватарами).
    Поведение прежнее: 3 попытки/1.0s, fallback `bot.download`."""
    if not hot.get("flags.download_enabled", settings.DOWNLOAD_ENABLED):            # облачный режим: как раньше
        await bot.download(media.file_id, destination=tmp_path)
        return
    # Epic 78 (D292): локальный Bot API возвращает относительный file_path,
    # файл лежит на диске в TELEGRAM_API_FILES_DIR/<bot_id>:<token>/.
    # Epic 79 hotfix (aiogram 3.31+ race): retry с задержкой (локальный API
    # успевает за ~1-2с), после чего — bot.download.
    max_attempts = 3

    async def _copy(src: Path) -> None:
        await asyncio.to_thread(shutil.copyfile, src, tmp_path)

    if await _read_local_source(bot, media.file_id, _copy,
                                attempts=max_attempts, sleep=1.0):
        return
    # Все retry исчерпаны. Последняя попытка: bot.download.
    # В локальном режиме (is_local=True) падает FileNotFoundError, если файл
    # всё ещё не на диске — но попытка лучше, чем молчание + 0 ответ.
    logger.warning("[transcribe] local file unavailable after %d attempts | "
                   "file_id=%s | falling back to bot.download",
                   max_attempts, media.file_id)
    await bot.download(media.file_id, destination=tmp_path)
