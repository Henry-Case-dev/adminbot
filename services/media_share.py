"""Раунд 3 (T-687) — подсистема публикации временных медиа для мультимодалки.

Единственный путь к «просмотру» нативных TG-видео и скачанных файлов через
OpenRouter: файл копируется в MEDIA_SHARE_DIR под случайным uuid-именем и
раздаётся короткоживущим HMAC-подписанным URL `/media/{file_id}?e=&s=`
(эндпоинт — web/app.py; наружу — Caddy, @DevOps T-704).

Безопасность (NFR-3): uuid-имена без привязки к Telegram file_id, подпись
HMAC-SHA256 (секрет ТОЛЬКО в env, R17: не логируется, URL с s= не логируем),
TTL из настроек, белый список расширений, отсутствие path-traversal (маска
file_id — эндпоинт строит путь из проверенного имени), каталог вне
web-статики. Публикация ОТКЛЮЧЕНА при пустом MEDIA_SHARE_SECRET — все вызовы
no-op (WARNING-лог), видео-ветки честно деградируют на STT.

NFR-5: копирование/удаление/чистка — asyncio.to_thread (не блокируем loop).
NFR-2: TTL-очистка ленивая — при каждой публикации + cleanup_expired() на
старте (бот.py on_startup).
"""
import asyncio
import dataclasses
import hashlib
import hmac
import logging
import re
import shutil
import time
import uuid
from pathlib import Path

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

_EXT_WHITELIST = frozenset({"mp4", "webm", "mov", "mkv", "avi"})
_SHARE_FILE_RE = re.compile(r"^[0-9a-f]{32}\.(mp4|webm|mov|mkv|avi)$")

# TTL < 60 сек запрещён на уровне настроек (_env_int_min); здесь — страховка.
_TTL_MIN_SECONDS = 60

# NFR-8: WARNING о выключенной публикации — один раз за процесс (не спамим).
_warned_disabled = False


@dataclasses.dataclass(frozen=True)
class ShareTicket:
    """Билет опубликованного файла (FR-B1)."""
    file_id: str          # "<uuid32>.<ext>"
    expires: int          # unix-ts
    sig: str              # hex HMAC-SHA256
    rel_url: str          # "/media/{file_id}?e={expires}&s={sig}"
    abs_url: str          # MEDIA_PUBLIC_BASE_URL + rel_url


def _secret() -> str:
    """Секрет подписи — горячая точка (keys.media_share_secret, R17)."""
    return str(hot.get("keys.media_share_secret", settings.MEDIA_SHARE_SECRET) or "")


def _share_dir() -> Path:
    return Path(hot.get("content.media_share_dir", settings.MEDIA_SHARE_DIR))


def _ttl_seconds() -> int:
    # Тут TTL ЧИСТКИ каталога (cleanup_expired). Публикация приходит со своим
    # ttl и клампит expires отдельно (now + max(ttl, 60), см. _publish_sync):
    # при PG-настройке < 60 URL живёт 60с, а чистка дожидается 900с —
    # рассинхрон БЕЗВРЕДЕН (файл обычно удаляется delete_file в finally,
    # иначе TTL-окно заведомо больше жизни URL) — fix-round 04.09 (m7).
    ttl = int(hot.get("limits.media_share_ttl_seconds",
                      settings.MEDIA_SHARE_TTL_SECONDS) or 0)
    if ttl < _TTL_MIN_SECONDS:
        logger.warning("[media_share] ttl=%d < %d — using default 900",
                       ttl, _TTL_MIN_SECONDS)
        return 900
    return ttl


def _max_bytes() -> int:
    mb = int(hot.get("limits.media_share_max_mb", settings.MEDIA_SHARE_MAX_MB) or 0)
    return max(mb, 0) * 1024 * 1024


def _public_base_url() -> str:
    return str(hot.get("content.media_public_base_url",
                       settings.MEDIA_PUBLIC_BASE_URL) or "").rstrip("/")


def enabled() -> bool:
    """Публикация включена только при заданном секрете (FR-B1)."""
    return bool(_secret())


def sign(file_id: str, expires: int) -> str:
    """hex HMAC-SHA256 по строке '{file_id}:{expires}' (3.1)."""
    return hmac.new(_secret().encode(),
                    f"{file_id}:{expires}".encode(),
                    hashlib.sha256).hexdigest()


def verify(file_id: str, expires: int, sig: str) -> bool:
    """Проверка подписи (hmac.compare_digest — без утечки по времени).
    Не-ASCII sig → False (compare_digest требует ASCII-строки; TypeError
    давал бы HTTP 500 на публичном /media вместо 403 — fix-round 04.09, M1)."""
    if not enabled():
        return False
    sig = str(sig)
    if not sig or not sig.isascii():
        return False
    expected = sign(file_id, int(expires))
    return hmac.compare_digest(sig, expected)


def build_media_url(file_id: str, expires: int) -> str:
    """Относительный URL `/media/{file_id}?e={expires}&s={sig}` (3.1)."""
    return f"/media/{file_id}?e={int(expires)}&s={sign(file_id, int(expires))}"


def cleanup_expired(now: int | None = None) -> int:
    """Ленивая чистка каталога: удалить файлы-копии старше TTL (mtime).
    Синхронная (оборачивается в to_thread вызывающими); no-op без секрета.
    Возвращает число удалённых файлов."""
    if not enabled():
        return 0
    now = int(time.time()) if now is None else int(now)
    ttl = _ttl_seconds()
    removed = 0
    share_dir = _share_dir()
    try:
        if not share_dir.exists():
            return 0
        for entry in share_dir.iterdir():
            if not entry.is_file() or not _SHARE_FILE_RE.match(entry.name):
                continue
            try:
                if entry.stat().st_mtime < now - ttl:
                    entry.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                logger.warning("[media_share] cleanup skip | file=%s",
                               entry.name, exc_info=True)
    except OSError:
        logger.warning("[media_share] cleanup failed", exc_info=True)
    if removed:
        logger.info("[media_share] cleanup | removed=%d", removed)
    return removed


def _publish_sync(src_path: str, ttl_seconds: int) -> ShareTicket | None:
    """Синхронное ядро публикации (3.1): no-op при пустом секрете; ext из
    исходника в белом списке (иначе no-op); размер > потолка → no-op;
    копия в MEDIA_SHARE_DIR/{uuid4.hex}.{ext} c предварительной ленивой
    TTL-чисткой каталога; возвращает ticket."""
    if not enabled():
        global _warned_disabled
        if not _warned_disabled:
            _warned_disabled = True
            logger.warning("[media_share] disabled (no secret) — STT fallback")
        return None
    src = Path(src_path)
    ext = str(src.suffix or "").lstrip(".").lower()
    if ext not in _EXT_WHITELIST:
        logger.warning("[media_share] ext not whitelisted | ext=%r", ext)
        return None
    try:
        size = src.stat().st_size
    except OSError:
        logger.warning("[media_share] source stat failed | file=%s",
                       src.name, exc_info=True)
        return None
    max_bytes = _max_bytes()
    if max_bytes > 0 and size > max_bytes:
        logger.info("[media_share] file too big (%d MB > %d MB) — no publish "
                    "| file=%s", size // (1024 * 1024),
                    max_bytes // (1024 * 1024), src.name)
        return None
    share_dir = _share_dir()
    try:
        share_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("[media_share] mkdir failed | dir=%s", share_dir,
                       exc_info=True)
        return None
    cleanup_expired()                    # ленивая TTL-чистка при публикации
    file_id = f"{uuid.uuid4().hex}.{ext}"
    dst = share_dir / file_id
    try:
        shutil.copyfile(str(src), str(dst))
    except OSError:
        logger.warning("[media_share] copy failed | file=%s", src.name,
                       exc_info=True)
        return None
    expires = int(time.time()) + max(int(ttl_seconds), _TTL_MIN_SECONDS)
    rel_url = build_media_url(file_id, expires)
    ticket = ShareTicket(
        file_id=file_id,
        expires=expires,
        sig=rel_url.rsplit("s=", 1)[-1],
        rel_url=rel_url,
        abs_url=f"{_public_base_url()}{rel_url}",
    )
    logger.info("[media_share] published | file_id=%s bytes=%d", file_id, size)
    return ticket


async def publish_media_file(src_path: str, ttl_seconds: int) -> ShareTicket | None:
    """Асинхронная публикация (NFR-5: копирование/чистка — в to_thread)."""
    return await asyncio.to_thread(_publish_sync, src_path, ttl_seconds)


async def delete_file(file_id: str) -> None:
    """Best-effort удаление опубликованного файла (в finally после каскада;
    TTL — страховка от падений/ретраев уровня)."""
    if not enabled():
        return
    if not _SHARE_FILE_RE.match(file_id):
        return
    path = _share_dir() / file_id
    try:
        await asyncio.to_thread(path.unlink, missing_ok=True)
        logger.info("[media_share] deleted | file_id=%s", file_id)
    except OSError:
        logger.warning("[media_share] delete failed | file_id=%s", file_id)
