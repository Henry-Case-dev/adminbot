"""Bugfix 04.09.2026 (Часть 1, FR-4) — общее скачивание TG-медиа в tmp.

Перенос из handlers/voice_transcription.py (_fetch_media_to_tmp, Epic 78,
D292/Section 79) БЕЗ изменения поведения: голосовые (voice_transcription),
кружочки и нативные видео (youtube.py Часть 1), «скачай»-нативные медиа
(handlers/video_download.py Часть 1b) ходят через один хелпер.

Гейт режима endpoint'а — фактическая aiogram-сессия
(`session.api.is_local`; при её отсутствии инфраструктурный `TELEGRAM_LOCAL`),
НЕ функциональный `flags.download_enabled`.
Локальный режим И file_path под корнем TELEGRAM_API_FILES_DIR (относительный
→ root/<bot_id:token>/<path>; абсолютный — только если он внутри корня;
контейнерный `/var/lib/telegram-bot-api/…` нормализуется к host-корню) →
копирование с диска; файла нет → облачный fallback (если разрешён).
Секреты (R17): строка '<bot_id>:<token>' нигде не логируется.

**P0 vision download (2026-11-17).** `services/mca_vision.py::download_telegram_file`
ходил мимо этого модуля (`bot.get_file` + `bot.download`): при локальном Bot
API `bot.download` читает файл С ДИСКА, и отсутствие файла давало общий
`OSError`, который vision-контур сворачивал в `vision_unavailable` без класса
(прод: 183 failed-события с пустым `error_json`). Теперь байты файла Bot API
получает ОДИН транспорт `download_api_file_bytes`:

  1. локальный Bot API (`session.api.is_local`) → файл с диска
     (`local_file_path`: контейнерный/относительный путь → host-корень),
     bounded-retry на появление файла;
  2. штатный транспорт aiogram (`download_file`) — в облачном режиме HTTP,
     в локальном режиме ещё одно чтение того же файла (прежнее поведение
     не ухудшается);
  3. облачный fallback `api.telegram.org/file/bot<token>/<path>` — только
     когда локальный файл недоступен/не прочитан. Env-рубильник
     `MEDIA_DOWNLOAD_CLOUD_FALLBACK` (default ON). Локальный Bot API сам
     cloud-файлы НЕ отдаёт (`--local` без `/file/bot…`), поэтому без этого
     шага «файла нет на диске» = потерянная картинка. F5 (security):
     `follow_redirects=False` — токен в пути не уходит на чужой хост по
     302; 3xx → типизированный `provider_error` (`redirect_refused`);
     TLS-verify не ослабляется.

**P0 voice-transcription recovery (2026-11-18).** Голос/кружок больше не
ходят отдельной тройкой `get_file` + `bot.download`: `fetch_media_to_tmp`
использует тот же транспорт (`download_api_file_to_path` — streaming-адаптер
`download_api_file_bytes` с теми же стадиями/классами). Локальный 400
«wrong file_id or the file is temporarily unavailable» — НЕ `invalid_file_id`
(файл мог не записаться на диск): это `local_read_failed` с ОДНОЙ попыткой и
правом облачного fallback; `invalid_file_id` терминален и определяется
облаком/формой id. Transient (timeout/network/5xx) — bounded retry. Режим
endpoint'а берётся из фактической aiogram-сессии, а при её отсутствии — из
инфраструктурного `TELEGRAM_LOCAL`; функциональный
`flags.download_enabled` endpoint НЕ выбирает.

Наружу — только байты либо `MediaDownloadError(stage, error_class)`
(`get_file` | `local_read` | `cloud_download`; классы `invalid_file_id`,
`missing_local_file`, `permission_denied`, `timeout`, `network`,
`oversized`, `unreadable_raster`, `provider_error`). R17: путь с
'<bot_id>:<token>', URL с токеном и приватные байты не попадают ни в
сообщения исключений, ни в логи (только stage/класс/хвост имени файла).
"""
import asyncio
import io
import logging
import os
import shutil
from pathlib import Path, PurePosixPath

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)


async def module_enabled(chat_id) -> bool:
    """Per-chat гейт МОДУЛЯ «Скачивание медиа» (MOD-ACL-UX-01 M2.1).

    Тонкий адаптер к каноническому резолверу: GLOBAL-дефолт
    `flags.download_enabled` → явный CHAT-override. Сам общий транспорт
    (`fetch_media_to_tmp`) этим гейтом не останавливается: голос/
    транскрипция/видео-выжимка ходят через него независимо, а решение
    «принимать ли новое скачивание этого чата» принимает потребитель
    (handler 4e / tool `download_media`).
    """
    from services import feature_gates
    return await feature_gates.module_enabled(
        chat_id, key="flags.download_enabled",
        default=getattr(settings, "DOWNLOAD_ENABLED", False))


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


# ════════════════════════════════════════════════════════════════════════════
# Единый bytes-транспорт Bot API (P0 vision download, 2026-11-17)
# ════════════════════════════════════════════════════════════════════════════

CLOUD_API_BASE = "https://api.telegram.org"
CLOUD_FALLBACK_ENV = "MEDIA_DOWNLOAD_CLOUD_FALLBACK"
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 30.0

STAGE_GET_FILE = "get_file"
STAGE_LOCAL_READ = "local_read"
STAGE_CLOUD_DOWNLOAD = "cloud_download"
STAGE_VALIDATE = "validate"

ERROR_INVALID_FILE_ID = "invalid_file_id"
ERROR_MISSING_LOCAL_FILE = "missing_local_file"
ERROR_LOCAL_READ_FAILED = "local_read_failed"
ERROR_PERMISSION_DENIED = "permission_denied"
ERROR_TIMEOUT = "timeout"
ERROR_NETWORK = "network"
ERROR_OVERSIZED = "oversized"
ERROR_UNREADABLE_RASTER = "unreadable_raster"
ERROR_PROVIDER_ERROR = "provider_error"

# Классы, которые транспорт обязан различать (приёмка LVS-VIS-03/VIS-07):
# missing_local_file | permission_denied | invalid_file_id | timeout | network |
# oversized | unreadable_raster | provider_error (+ local_read_failed — прочие
# ошибки чтения файла FС, чтобы «неизвестное» не маскировалось под права).
ERROR_CLASSES = frozenset({
    ERROR_INVALID_FILE_ID, ERROR_MISSING_LOCAL_FILE, ERROR_LOCAL_READ_FAILED,
    ERROR_PERMISSION_DENIED, ERROR_TIMEOUT, ERROR_NETWORK, ERROR_OVERSIZED,
    ERROR_UNREADABLE_RASTER, ERROR_PROVIDER_ERROR,
})


class MediaDownloadError(Exception):
    """Классифицированный отказ получения байтов файла Bot API.

    `stage` — где именно отказало (`get_file` | `local_read` |
    `cloud_download`); `error_class` — R17-safe класс из `ERROR_CLASSES`;
    `retryable` — стоит ли повторять в рамках текущего вызова (появление
    файла/сеть), либо класс постоянный (невалидный file_id, размер).

    R17: сообщение исключения — только 'stage:class' (никаких путей с
    '<bot_id>:<token>', URL Bot API или приватных байтов); первопричина
    подавлена (`from None` у вызывающих), чтобы traceback не печатал URL.
    """

    def __init__(self, stage: str, error_class: str, detail: str = "",
                 *, retryable: bool = True) -> None:
        self.stage = str(stage or "")
        self.error_class = str(error_class or ERROR_PROVIDER_ERROR)
        self.detail = str(detail or "")
        self.retryable = bool(retryable)
        super().__init__(f"{self.stage}:{self.error_class}")


def classify_transport_error(exc: BaseException) -> tuple[str, bool]:
    """(класс, retryable) для исключения транспорта — без утечки текста.

    R17: возвращаются только строки классов; сообщение исключения
    используется локально лишь как признак «file not found/invalid» и
    наружу не отдаётся (в нём бывает полный путь/URL с токеном).
    """
    name = type(exc).__name__
    low_name = name.lower()
    text = ""
    try:
        text = str(exc).lower()
    except Exception:            # pragma: no cover - защита от злых __str__
        text = ""
    if isinstance(exc, asyncio.TimeoutError) or "timeout" in low_name:
        return ERROR_TIMEOUT, True
    if isinstance(exc, PermissionError) or "permission" in low_name:
        return ERROR_PERMISSION_DENIED, True
    if isinstance(exc, FileNotFoundError):
        return ERROR_MISSING_LOCAL_FILE, True
    if ("notfound" in low_name or "not found" in text
            or "invalid file" in text or "file_id" in text
            or "identifier" in text):
        return ERROR_INVALID_FILE_ID, False
    if "forbidden" in low_name or "unauthorized" in low_name:
        return ERROR_PERMISSION_DENIED, True
    if isinstance(exc, OSError) or any(
            token in low_name
            for token in ("client", "network", "connector", "connect")):
        return ERROR_NETWORK, True
    return ERROR_PROVIDER_ERROR, True


def local_api_enabled(bot) -> bool:
    """Использует ли бот локальный Bot API (`session.api.is_local`).

    Источник истины — фактическая сессия aiogram (прод-путь
    `services.local_bot_api.build_local_api_session`), а при её отсутствии —
    инфраструктурная конфигурация `TELEGRAM_LOCAL` (тот же сигнал, что у
    контейнера telegram-bot-api). Функциональный флаг
    `flags.download_enabled` сюда НЕ входит: выключение функции модуля не
    меняет выбранный endpoint и не маскирует расхождение режимов."""
    from services.local_bot_api import bot_api_mode
    return bot_api_mode(bot)["mode"] == "local"


def cloud_fallback_enabled() -> bool:
    """Env-рубильник облачного fallback (`MEDIA_DOWNLOAD_CLOUD_FALLBACK`).

    Default ON: локальный Bot API `--local` не отдаёт файлы по HTTP, поэтому
    без этого шага «файла нет на диске» = потерянная картинка (прод-факт
    2026-11-16/17). Значения «0/false/off/no/» — выключено."""
    raw = os.getenv(CLOUD_FALLBACK_ENV, "1")
    return str(raw).strip().lower() not in ("0", "false", "off", "no", "")


def safe_path_tail(file_path) -> str:
    """R17-safe хвост пути файла для логов (без каталога токена).

    Каталог локального Bot API называется '<bot_id>:<token>' — сегменты с
    ':' отбрасываются; остаются максимум два последних сегмента
    (`photos/file_1.jpg`)."""
    text = str(file_path or "").replace("\\", "/")
    parts = [p for p in text.split("/") if p not in ("", ".", "..")]
    parts = [p for p in parts if ":" not in p]
    return "/".join(parts[-2:])


def cloud_relative_path(bot, file_path) -> str | None:
    """Относительный путь Bot API для облачного fallback (None — unsafe).

    Принимает относительный (`photos/file_1.jpg`), контейнерный
    (`/var/lib/telegram-bot-api/<bot_id>:<token>/photos/…`) и
    host-абсолютный путь: отбрасывает корень и каталог токена. Пути с '..'
    и пустые — None (в облако произвольный путь не уходит)."""
    text = str(file_path or "").replace("\\", "/").strip()
    if not text:
        return None
    raw_parts = text.split("/")
    if any(part == ".." for part in raw_parts):
        return None
    if text.startswith(CONTAINER_API_FILES_ROOT + "/"):
        text = text[len(CONTAINER_API_FILES_ROOT) + 1:]
    parts = [p for p in text.split("/") if p not in ("", ".")]
    subdir = ""
    try:
        subdir = local_files_subdir(bot)
    except Exception:
        subdir = ""
    for idx, part in enumerate(parts):
        # Каталог токена: '<bot_id>:<token>' (или 'голый' secret-каталог).
        if part == subdir or (":" in part and part.split(":", 1)[0].isdigit()):
            parts = parts[idx + 1:]
            break
    rel = "/".join(parts)
    return rel or None


def _bot_token(bot) -> str:
    """Токен бота для облачного fallback (никогда не логируется)."""
    try:
        token = str(getattr(bot, "token", "") or "")
    except Exception:
        token = ""
    if token:
        return token
    try:
        return str(getattr(settings, "API_TOKEN", "") or "")
    except Exception:
        return ""


def _size_guard(data: bytes, max_bytes, stage: str) -> bytes:
    """Struct-проверка размера (R17: в сообщении только лимит)."""
    limit = int(max_bytes) if max_bytes else 0
    if limit > 0 and len(data) > limit:
        raise MediaDownloadError(stage, ERROR_OVERSIZED,
                                 f"file exceeds {limit} bytes",
                                 retryable=False)
    return data


async def read_local_path_bytes(src: Path, *, max_bytes: int | None = None
                                ) -> bytes:
    """Байты уже резолвленного файла (stat → размер → read_bytes).

    Отдельная функция — единая точка чтения локального файла для bytes-
    потребителей (`read_host_file_bytes`, `download_api_file_bytes`).
    Ошибки чтения (FileNotFoundError/PermissionError/OSError) пробрасываются
    как есть — класс определяет вызывающий."""
    def _read() -> bytes:
        size = src.stat().st_size
        limit = int(max_bytes) if max_bytes else 0
        if limit > 0 and size > limit:
            raise MediaDownloadError(STAGE_LOCAL_READ, ERROR_OVERSIZED,
                                     f"file exceeds {limit} bytes",
                                     retryable=False)
        return src.read_bytes()

    return await asyncio.to_thread(_read)


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
        data = await read_local_path_bytes(src)
    except (OSError, MediaDownloadError):
        return None
    return data


async def _aiogram_transport_bytes(bot, tg_file, file_id: str,
                                   file_path: str | None, *,
                                   timeout: float) -> bytes:
    """Штатный транспорт aiogram (cloud — HTTP, local — диск).

    Приоритет — `download_file(file_path)` (без повторного getFile).
    Объект `tg_file` нужен для двойников/крупных файлов, у которых
    `file_path` пуст: `bot.download(tg_file, ...)` — прежний контракт."""
    buffer = io.BytesIO()
    download_file = getattr(bot, "download_file", None)
    if file_path and callable(download_file):
        await download_file(
            file_path, destination=buffer,
            timeout=max(1, int(timeout or DEFAULT_DOWNLOAD_TIMEOUT_SECONDS)))
    elif tg_file is not None:
        await bot.download(tg_file, destination=buffer)
    else:
        await bot.download(file_id, destination=buffer)
    return buffer.getvalue()


async def _cloud_api_file_path(token: str, file_id: str, *,
                               timeout: float) -> str:
    """Облачный getFile (api.telegram.org) → file_path. R17: URL с токеном
    не логируется; наружу — только класс ошибки.

    F5 (security): `follow_redirects=False` — токен в пути не должен уйти на
    чужой хост по 302; любой 3xx — типизированный отказ, TLS-verify не
    ослабляется."""
    url = f"{CLOUD_API_BASE}/bot{token}/getFile"
    try:
        async with httpx.AsyncClient(timeout=timeout,
                                     follow_redirects=False) as client:
            response = await client.get(url, params={"file_id": file_id})
            status = int(response.status_code)
            payload = response.json() if status == 200 else {}
    except Exception as exc:
        cls, retryable = classify_transport_error(exc)
        if cls in (ERROR_MISSING_LOCAL_FILE, ERROR_INVALID_FILE_ID):
            cls = ERROR_NETWORK
        raise MediaDownloadError(STAGE_CLOUD_DOWNLOAD, cls, "",
                                 retryable=retryable) from None
    if status in (400, 404):
        raise MediaDownloadError(STAGE_CLOUD_DOWNLOAD, ERROR_INVALID_FILE_ID,
                                 f"http_{status}", retryable=False)
    if 300 <= status < 400:
        # Редирект с токеном в URL не выполняется принципиально.
        raise MediaDownloadError(STAGE_CLOUD_DOWNLOAD, ERROR_PROVIDER_ERROR,
                                 f"redirect_refused/http_{status}",
                                 retryable=False)
    if status != 200:
        raise MediaDownloadError(STAGE_CLOUD_DOWNLOAD, ERROR_PROVIDER_ERROR,
                                 f"http_{status}", retryable=status >= 500)
    result = payload.get("result") if isinstance(payload, dict) else None
    path = str((result or {}).get("file_path") or "") \
        if isinstance(result, dict) else ""
    if not path:
        raise MediaDownloadError(STAGE_CLOUD_DOWNLOAD, ERROR_INVALID_FILE_ID,
                                 "no file_path", retryable=False)
    return path


async def _default_cloud_fetch(token: str, file_id: str, rel_path: str,
                               *, timeout: float, max_bytes=None) -> bytes:
    """Облачный fallback: файл Bot API с api.telegram.org.

    Используется только когда локальный файл недоступен/не прочитан.
    F5 (security): `follow_redirects=False` — токен в пути не уходит на
    адрес редиректа; 3xx — типизированный `provider_error`
    (`redirect_refused`), TLS-verify не ослабляется (httpx default).
    R17: URL (с токеном) не логируется и не попадает в текст исключения;
    наружу — только `MediaDownloadError(stage, class)`."""
    if not token:
        raise MediaDownloadError(STAGE_CLOUD_DOWNLOAD, ERROR_PROVIDER_ERROR,
                                 "no bot token", retryable=False)
    path = str(rel_path or "").lstrip("/") \
        or await _cloud_api_file_path(token, file_id, timeout=timeout)
    if not path:
        raise MediaDownloadError(STAGE_CLOUD_DOWNLOAD, ERROR_INVALID_FILE_ID,
                                 "no file_path", retryable=False)
    url = f"{CLOUD_API_BASE}/file/bot{token}/{path}"
    limit = int(max_bytes) if max_bytes else 0
    try:
        async with httpx.AsyncClient(timeout=timeout,
                                     follow_redirects=False) as client:
            async with client.stream("GET", url) as response:
                status = int(response.status_code)
                if status == 404:
                    raise MediaDownloadError(
                        STAGE_CLOUD_DOWNLOAD, ERROR_INVALID_FILE_ID,
                        "http_404", retryable=False)
                if 300 <= status < 400:
                    # Редирект с токеном в URL не выполняется принципиально.
                    raise MediaDownloadError(
                        STAGE_CLOUD_DOWNLOAD, ERROR_PROVIDER_ERROR,
                        f"redirect_refused/http_{status}", retryable=False)
                if status >= 400:
                    raise MediaDownloadError(
                        STAGE_CLOUD_DOWNLOAD, ERROR_PROVIDER_ERROR,
                        f"http_{status}", retryable=status >= 500)
                buffer = bytearray()
                async for chunk in response.aiter_bytes():
                    buffer.extend(chunk)
                    if limit > 0 and len(buffer) > limit:
                        raise MediaDownloadError(
                            STAGE_CLOUD_DOWNLOAD, ERROR_OVERSIZED,
                            f"file exceeds {limit} bytes", retryable=False)
                return bytes(buffer)
    except MediaDownloadError:
        raise
    except Exception as exc:
        cls, retryable = classify_transport_error(exc)
        if cls in (ERROR_MISSING_LOCAL_FILE, ERROR_INVALID_FILE_ID):
            cls = ERROR_NETWORK
        raise MediaDownloadError(STAGE_CLOUD_DOWNLOAD, cls, "",
                                 retryable=retryable) from None


async def download_api_file_bytes(bot, file_id: str, *, site: str = "media",
                                  attempts: int = 3, sleep: float = 1.0,
                                  timeout: float | None = None,
                                  max_bytes: int | None = None,
                                  cloud_fetcher=None,
                                  diagnostics: dict | None = None) -> bytes:
    """ЕДИНЫЙ транспорт байтов файла Bot API (local → cloud).

    Порядок (см. docstring модуля): локальный файл с диска (только локальный
    Bot API; bounded-retry на появление файла) → штатный транспорт aiogram →
    облачный fallback. Любой отказ — `MediaDownloadError` с полями
    `stage`/`error_class`/`retryable` (R17-safe). `diagnostics` (необязателен)
    заполняется последней стадией/классом для вызывающего контура
    наблюдаемости; значения не содержат путей/секретов.

    `cloud_fetcher(token, file_id, rel_path, *, timeout, max_bytes)` —
    точка инъекции для тестов; prod-путь — `_default_cloud_fetch`."""
    text_id = str(file_id or "").strip()
    if not text_id:
        raise MediaDownloadError(STAGE_GET_FILE, ERROR_INVALID_FILE_ID,
                                 "empty file id", retryable=False)
    attempts = max(1, int(attempts or 1))
    timeout = float(timeout or DEFAULT_DOWNLOAD_TIMEOUT_SECONDS)
    diag: dict = diagnostics if diagnostics is not None else {}
    last_stage = STAGE_LOCAL_READ
    last_class = ERROR_MISSING_LOCAL_FILE
    last_retryable = True
    file_path = None
    tg_file = None
    is_local = local_api_enabled(bot)

    if is_local:
        for attempt in range(1, attempts + 1):
            try:
                tg_file = await bot.get_file(text_id)
                file_path = getattr(tg_file, "file_path", None)
            except Exception as exc:
                cls, retryable = classify_transport_error(exc)
                # P0 18.11.2026 (prod-диагноз): локальный 400
                # «wrong file_id or the file is temporarily unavailable» —
                # НЕ доказательство невалидного id: файл мог не записаться на
                # диск (uid 101 без права записи). Такой отказ — local
                # read failure с правом облачного fallback; invalid_file_id
                # авторитетно определяет только облако/форма id.
                if cls == ERROR_INVALID_FILE_ID:
                    cls = ERROR_LOCAL_READ_FAILED
                    retryable = False
                diag.update(stage=STAGE_GET_FILE, error_class=cls,
                            attempt=attempt)
                last_stage, last_class, last_retryable = (
                    STAGE_GET_FILE, cls, retryable)
                logger.warning("[%s] get_file failed (attempt %d/%d) | "
                               "file_id=%s | %s", site, attempt, attempts,
                               text_id, type(exc).__name__)
                file_path = None
                if not retryable:
                    break
                if attempt < attempts:
                    await asyncio.sleep(sleep)
                continue
            diag.pop("error_class", None)
            diag.update(stage="", attempt=attempt)
            src = local_file_path(bot, file_path)
            if src is None:
                last_stage = STAGE_LOCAL_READ
                last_class = ERROR_MISSING_LOCAL_FILE
                last_retryable = True
                logger.warning("[%s] local path unavailable (attempt %d/%d) | "
                               "tail=%s", site, attempt, attempts,
                               safe_path_tail(file_path))
            else:
                try:
                    data = await read_local_path_bytes(
                        src, max_bytes=max_bytes)
                    diag["outcome"] = "local_read"
                    return data
                except MediaDownloadError:
                    raise            # oversized — постоянный класс
                except FileNotFoundError:
                    last_stage, last_class = (STAGE_LOCAL_READ,
                                              ERROR_MISSING_LOCAL_FILE)
                except PermissionError:
                    last_stage, last_class = (STAGE_LOCAL_READ,
                                              ERROR_PERMISSION_DENIED)
                except OSError:
                    last_stage, last_class = (STAGE_LOCAL_READ,
                                              ERROR_LOCAL_READ_FAILED)
                last_retryable = True
                diag.update(stage=last_stage, error_class=last_class)
                logger.warning("[%s] local file unavailable (attempt %d/%d) | "
                               "tail=%s | class=%s", site, attempt, attempts,
                               safe_path_tail(file_path), last_class)
            if attempt < attempts:
                await asyncio.sleep(sleep)
    else:
        # Облачный режим: локальный диск не участвует (прежняя семантика).
        try:
            tg_file = await bot.get_file(text_id)
            file_path = getattr(tg_file, "file_path", None)
        except Exception as exc:
            cls, retryable = classify_transport_error(exc)
            diag.update(stage=STAGE_GET_FILE, error_class=cls)
            last_stage, last_class, last_retryable = (
                STAGE_GET_FILE, cls, retryable)

    # 2) Штатный транспорт aiogram: в облаке — HTTP, в локальном режиме —
    # ещё одно чтение того же файла (прежнее поведение не ухудшается).
    if tg_file is not None or file_path:
        transport_stage = STAGE_LOCAL_READ if is_local else STAGE_CLOUD_DOWNLOAD
        try:
            data = await _aiogram_transport_bytes(bot, tg_file, text_id,
                                                  file_path, timeout=timeout)
        except Exception as exc:
            cls, retryable = classify_transport_error(exc)
            # В локальном режиме стадия 1 (чтение того же файла с диска) —
            # авторитетная: повторное чтение через aiogram не должно
            # «понижать» уже определённый класс (например, permission_denied
            # → missing_local_file). В облаке это основной транспорт.
            if not is_local:
                last_stage, last_class, last_retryable = (
                    transport_stage, cls, retryable)
                diag.update(stage=last_stage, error_class=cls)
            logger.warning("[%s] bot transport failed | class=%s",
                           site, cls)
        else:
            if data:
                data = _size_guard(data, max_bytes, transport_stage)
                diag["outcome"] = "aiogram_transport"
                return data

    # 3) Облачный fallback. Только локальный Bot API: локальный сервер в
    # `--local` НЕ отдаёт файлы по HTTP, поэтому «файла нет на диске» без
    # этого шага = потерянная картинка. В облачном режиме штатный транспорт
    # aiogram уже облачный (второй облачный путь не нужен).
    last_error: MediaDownloadError | None = None
    if (is_local and cloud_fallback_enabled()
            and last_class not in (ERROR_INVALID_FILE_ID, ERROR_OVERSIZED)):
        fetcher = cloud_fetcher or _default_cloud_fetch
        try:
            data = await fetcher(_bot_token(bot), text_id,
                                 cloud_relative_path(bot, file_path) or "",
                                 timeout=timeout, max_bytes=max_bytes)
        except MediaDownloadError as exc:
            last_error = exc
            last_stage = exc.stage or STAGE_CLOUD_DOWNLOAD
            last_class = exc.error_class
            last_retryable = exc.retryable
            diag.update(stage=last_stage, error_class=last_class)
            logger.warning("[%s] cloud fallback failed | class=%s",
                           site, last_class)
        except Exception as exc:
            cls, retryable = classify_transport_error(exc)
            last_stage, last_class, last_retryable = (
                STAGE_CLOUD_DOWNLOAD, cls, retryable)
            diag.update(stage=last_stage, error_class=last_class)
            logger.warning("[%s] cloud fallback failed | class=%s",
                           site, cls)
        else:
            data = _size_guard(bytes(data or b""), max_bytes,
                               STAGE_CLOUD_DOWNLOAD)
            if data:
                diag["outcome"] = "cloud_fallback"
                logger.warning("[%s] cloud fallback used | file_id=%s | "
                               "local=%s", site, text_id, last_class)
                return data

    diag.setdefault("stage", last_stage)
    diag.setdefault("error_class", last_class)
    diag["outcome"] = "failed"
    if last_error is not None:
        raise last_error
    raise MediaDownloadError(last_stage, last_class,
                             retryable=last_retryable)


async def download_api_file_to_path(
        bot, file_id: str, destination, *, site: str = "media",
        attempts: int = 3, sleep: float = 1.0,
        timeout: float | None = None, max_bytes: int | None = None,
        cloud_fetcher=None, diagnostics: dict | None = None) -> None:
    """Streaming-адаптер ЕДИНОГО транспорта: байты файла Bot API → файл.

    Те же стадии/классы, что у `download_api_file_bytes` (get_file |
    local_read | cloud_download | validate), но без буферизации всего файла:
    локальный Bot API копирует файл с диска, aiogram пишет поток в
    destination, облачный fallback использует общий `_default_cloud_fetch`.
    Нужен голосу/кружку/нативному видео, где файл не помещается в памяти
    без нужды (voice — маленький, видео — нет).

    Политика отказов: локальный 400 не выдаётся за `invalid_file_id`
    (это `local_read_failed`, ОДНА попытка, облачный fallback разрешён);
    `invalid_file_id` — только авторитетный ответ облака/форма id, он
    терминален и без fallback. timeout/network/5xx — bounded retry. 0 байт
    после транспорта — не успех (обрыв), а повторяемый отказ. Наружу — только
    `MediaDownloadError`; R17: полный file_id/путь/URL не логируются
    (только id-префикс и хвост имени файла).
    """
    text_id = str(file_id or "").strip()
    if not text_id:
        raise MediaDownloadError(STAGE_GET_FILE, ERROR_INVALID_FILE_ID,
                                 "empty file id", retryable=False)
    if not destination:
        raise MediaDownloadError(STAGE_VALIDATE, ERROR_PROVIDER_ERROR,
                                 "no destination", retryable=False)
    attempts = max(1, int(attempts or 1))
    timeout = float(timeout or DEFAULT_DOWNLOAD_TIMEOUT_SECONDS)
    diag: dict = diagnostics if diagnostics is not None else {}
    is_local = local_api_enabled(bot)
    file_path = None
    tg_file = None
    last_stage = STAGE_LOCAL_READ if is_local else STAGE_GET_FILE
    last_class = ERROR_MISSING_LOCAL_FILE if is_local else ERROR_PROVIDER_ERROR
    last_retryable = True
    permanent = (ERROR_INVALID_FILE_ID, ERROR_PERMISSION_DENIED)

    if is_local:
        # 1) Локальный Bot API: файл уже на диске хоста (bind-mount).
        # Повторяем только появление файла/transient-ошибки; постоянный
        # отказ Telegram не превращаем в 3 одинаковых запроса.
        for attempt in range(1, attempts + 1):
            try:
                tg_file = await bot.get_file(text_id)
                file_path = getattr(tg_file, "file_path", None)
            except Exception as exc:
                cls, retryable = classify_transport_error(exc)
                # P0 18.11.2026 (prod-диагноз): локальный 400 «wrong file_id or
                # the file is temporarily unavailable» НЕ доказывает
                # невалидный id — файл мог не записаться на диск. Это local
                # read failure с правом облачного fallback; invalid_file_id
                # авторитетно определяет облако/форма id.
                if cls == ERROR_INVALID_FILE_ID:
                    cls = ERROR_LOCAL_READ_FAILED
                    retryable = False
                diag.update(stage=STAGE_GET_FILE, error_class=cls,
                            attempt=attempt)
                last_stage, last_class, last_retryable = (
                    STAGE_GET_FILE, cls, retryable)
                logger.warning(
                    "[%s] get_file failed (attempt %d/%d) | id_prefix=%s | "
                    "%s", site, attempt, attempts, _id_prefix(text_id),
                    type(exc).__name__)
                tg_file = None
                file_path = None
                if not retryable or cls in permanent:
                    break
                if attempt < attempts:
                    await asyncio.sleep(sleep)
                continue
            diag.pop("error_class", None)
            diag.update(stage="", attempt=attempt)
            src = local_file_path(bot, file_path)
            if src is None:
                last_stage = STAGE_LOCAL_READ
                last_class = ERROR_MISSING_LOCAL_FILE
                last_retryable = True
                logger.warning(
                    "[%s] local path unavailable (attempt %d/%d) | "
                    "tail=%s", site, attempt, attempts,
                    safe_path_tail(file_path))
            else:
                try:
                    await _copy_local_file_to_path(
                        src, destination, max_bytes)
                    diag["outcome"] = "local_read"
                    return
                except MediaDownloadError:
                    raise            # oversized — постоянный класс
                except FileNotFoundError:
                    last_stage, last_class = (STAGE_LOCAL_READ,
                                              ERROR_MISSING_LOCAL_FILE)
                except PermissionError:
                    last_stage, last_class = (STAGE_LOCAL_READ,
                                              ERROR_PERMISSION_DENIED)
                except OSError:
                    last_stage, last_class = (STAGE_LOCAL_READ,
                                              ERROR_LOCAL_READ_FAILED)
                last_retryable = last_class != ERROR_PERMISSION_DENIED
                diag.update(stage=last_stage, error_class=last_class)
                logger.warning(
                    "[%s] local file unavailable (attempt %d/%d) | tail=%s "
                    "| class=%s", site, attempt, attempts,
                    safe_path_tail(file_path), last_class)
                if last_class in permanent:
                    break
            if attempt < attempts:
                await asyncio.sleep(sleep)
        # В локальном режиме второе чтение того же файла через aiogram не
        # помогает: сразу облачный fallback (если разрешён).
    else:
        # 2) Облачный режим: getFile → штатный транспорт aiogram. Сессия
        # облачная, диск хоста не участвует.
        for attempt in range(1, attempts + 1):
            try:
                tg_file = await bot.get_file(text_id)
                file_path = getattr(tg_file, "file_path", None)
            except Exception as exc:
                cls, retryable = classify_transport_error(exc)
                diag.update(stage=STAGE_GET_FILE, error_class=cls,
                            attempt=attempt)
                last_stage, last_class, last_retryable = (
                    STAGE_GET_FILE, cls, retryable)
                logger.warning(
                    "[%s] get_file failed (attempt %d/%d) | id_prefix=%s | "
                    "%s", site, attempt, attempts, _id_prefix(text_id),
                    type(exc).__name__)
                tg_file = None
                if not retryable or cls in permanent:
                    break
                if attempt < attempts:
                    await asyncio.sleep(sleep)
                continue
            diag.pop("error_class", None)
            diag.update(stage="", attempt=attempt)
            break
        if tg_file is None and not file_path:
            diag.setdefault("stage", last_stage)
            diag.setdefault("error_class", last_class)
            diag["outcome"] = "failed"
            raise MediaDownloadError(last_stage, last_class,
                                     retryable=last_retryable)
        for attempt in range(1, attempts + 1):
            try:
                await _aiogram_transport_to_path(
                    bot, tg_file, text_id, file_path, destination,
                    timeout=timeout)
                _check_destination(destination, max_bytes,
                                   STAGE_CLOUD_DOWNLOAD)
                diag["outcome"] = "aiogram_transport"
                return
            except MediaDownloadError:
                raise
            except Exception as exc:
                cls, retryable = classify_transport_error(exc)
                last_stage, last_class, last_retryable = (
                    STAGE_CLOUD_DOWNLOAD, cls, retryable)
                diag.update(stage=last_stage, error_class=cls,
                            attempt=attempt)
                logger.warning(
                    "[%s] bot transport failed (attempt %d/%d) | "
                    "id_prefix=%s | class=%s", site, attempt, attempts,
                    _id_prefix(text_id), cls)
                if not retryable or cls in permanent:
                    break
                if attempt < attempts:
                    await asyncio.sleep(sleep)

    # 3) Облачный fallback — только локальный Bot API и только когда он
    # разрешён. Постоянный local-отказ (400/права/файла нет) — как раз повод
    # получить авторитетный ответ облака; не повторяем в облаке только
    # невалидный id (его определило облако) и превышение размера.
    if (is_local and cloud_fallback_enabled()
            and last_class not in (ERROR_INVALID_FILE_ID, ERROR_OVERSIZED)):
        fetcher = cloud_fetcher or _default_cloud_fetch
        try:
            data = await fetcher(_bot_token(bot), text_id,
                                 cloud_relative_path(bot, file_path) or "",
                                 timeout=timeout, max_bytes=max_bytes)
        except MediaDownloadError as exc:
            last_stage = exc.stage or STAGE_CLOUD_DOWNLOAD
            last_class = exc.error_class
            last_retryable = exc.retryable
            diag.update(stage=last_stage, error_class=last_class)
            logger.warning("[%s] cloud fallback failed | id_prefix=%s | "
                           "class=%s", site, _id_prefix(text_id), last_class)
        except Exception as exc:
            cls, retryable = classify_transport_error(exc)
            last_stage, last_class, last_retryable = (
                STAGE_CLOUD_DOWNLOAD, cls, retryable)
            diag.update(stage=last_stage, error_class=last_class)
            logger.warning("[%s] cloud fallback failed | id_prefix=%s | "
                           "class=%s", site, _id_prefix(text_id), cls)
        else:
            await _write_bytes_to_path(destination, bytes(data or b""),
                                       max_bytes)
            diag["outcome"] = "cloud_fallback"
            logger.warning("[%s] cloud fallback used | id_prefix=%s | "
                           "local=%s", site, _id_prefix(text_id), last_class)
            return

    diag.setdefault("stage", last_stage)
    diag.setdefault("error_class", last_class)
    diag["outcome"] = "failed"
    raise MediaDownloadError(last_stage, last_class,
                             retryable=last_retryable)


def _id_prefix(file_id) -> str:
    """R17-safe префикс file_id для логов (полный идентификатор не пишем)."""
    text = str(file_id or "")
    return text[:6]


async def _copy_local_file_to_path(src: Path, destination,
                                   max_bytes) -> None:
    """Копия локального файла Bot API в destination с проверкой размера."""
    def _copy() -> None:
        size = src.stat().st_size
        limit = int(max_bytes) if max_bytes else 0
        if limit > 0 and size > limit:
            raise MediaDownloadError(STAGE_VALIDATE, ERROR_OVERSIZED,
                                     f"file exceeds {limit} bytes",
                                     retryable=False)
        shutil.copyfile(src, destination)

    await asyncio.to_thread(_copy)


async def _write_bytes_to_path(destination, data: bytes, max_bytes) -> None:
    """Запись готовых байтов (cloud fallback) с проверкой размера."""
    limit = int(max_bytes) if max_bytes else 0
    if limit > 0 and len(data) > limit:
        raise MediaDownloadError(STAGE_VALIDATE, ERROR_OVERSIZED,
                                 f"file exceeds {limit} bytes",
                                 retryable=False)
    if not data:
        raise MediaDownloadError(STAGE_CLOUD_DOWNLOAD, ERROR_PROVIDER_ERROR,
                                 "empty file", retryable=True)

    def _write() -> None:
        with open(destination, "wb") as fh:
            fh.write(data)

    await asyncio.to_thread(_write)


def _check_destination(destination, max_bytes, stage: str) -> None:
    """Проверка записанного файла: не пустой и не больше лимита."""
    try:
        size = os.path.getsize(destination)
    except OSError:
        raise MediaDownloadError(stage, ERROR_LOCAL_READ_FAILED,
                                 "destination unavailable",
                                 retryable=True) from None
    limit = int(max_bytes) if max_bytes else 0
    if limit > 0 and size > limit:
        raise MediaDownloadError(STAGE_VALIDATE, ERROR_OVERSIZED,
                                 f"file exceeds {limit} bytes",
                                 retryable=False)
    if size <= 0:
        raise MediaDownloadError(stage, ERROR_PROVIDER_ERROR,
                                 "empty file", retryable=True)


async def _aiogram_transport_to_path(bot, tg_file, file_id, file_path,
                                     destination, *, timeout: float) -> None:
    """Штатный транспорт aiogram: поток в destination (не в память)."""
    download_file = getattr(bot, "download_file", None)
    if file_path and callable(download_file):
        await download_file(
            file_path, destination=destination,
            timeout=max(1, int(timeout or DEFAULT_DOWNLOAD_TIMEOUT_SECONDS)))
    elif tg_file is not None:
        await bot.download(tg_file, destination=destination)
    else:
        await bot.download(file_id, destination=destination)


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
            cls, retryable = classify_transport_error(exc)
            logger.warning("[%s] get_file failed (attempt %d/%d) | "
                           "file_id_prefix=%s | %s",
                           site, attempt, attempts, _id_prefix(file_id),
                           type(exc).__name__)
            # Постоянный отказ Telegram (invalid file_id/auth) не повторяем:
            # 3 одинаковых запроса не меняют ответ. Transient — повторяем,
            # чтобы файл успел появиться.
            if not retryable or cls in (ERROR_INVALID_FILE_ID,
                                        ERROR_PERMISSION_DENIED):
                return False
        src = local_file_path(bot, file_path)
        if src is not None:
            try:
                if src.exists():
                    await on_found(src)
                    return True
                logger.warning(
                    "[%s] local api file missing (attempt %d/%d) | tail=%s",
                    site, attempt, attempts, safe_path_tail(file_path))
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


async def fetch_media_to_tmp(bot, media, tmp_path, *, site: str = "media",
                             max_bytes: int | None = None) -> None:
    """Получить медиа Bot API во tmp-файл ОДНИМ транспортом.

    P0 voice-transcription recovery (18.11.2026): раньше голос/кружок шли
    отдельной тройкой `bot.get_file` + `bot.download` (постоянный 400
    повторялся 3 раза, а «fallback» был тем же облачным путём). Теперь это
    streaming-адаптер `download_api_file_to_path` того же транспорта, что у
    Vision: стадии `get_file|local_read|cloud_download|validate`, классы
    `invalid_file_id|missing_local_file|permission_denied|timeout|network|
    oversized|provider_error`. Постоянный отказ не повторяется, transient —
    bounded retry; облачный fallback — только при разрешённом
    `MEDIA_DOWNLOAD_CLOUD_FALLBACK` и только из локального режима.

    Режим endpoint'а — фактическая aiogram-сессия (или инфраструктурный
    `TELEGRAM_LOCAL`), НЕ функциональный `flags.download_enabled`: горячее
    выключение модуля не меняет выбранный API и не маскирует расхождение.
    Ошибки — типизированные `MediaDownloadError` (R17: без полного file_id,
    пути `<bot_id>:<token>` и URL с токеном); temp-файл убирает вызывающий.
    """
    file_id = getattr(media, "file_id", None)
    await download_api_file_to_path(bot, file_id, tmp_path, site=site,
                                    max_bytes=max_bytes)
