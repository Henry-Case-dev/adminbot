"""Раунд 10.24 (F14, ADR-1024-15 §2.3/§4.1) — единый резолвер нативного медиа.

Устраняет дублирование квалификации «видео vs видео-документ» между
``handlers/youtube.py`` (медиа-ветка 0e) и ``handlers/video_download.py``
(Fast-Track 4e). Единственный источник:
``document_is_video`` / ``resolve_reply_video`` / ``media_suffix`` /
``download_to_tmp``.

Потребители:
* ``handlers/youtube.py`` — делегирует ``_document_is_video`` /
  ``_resolve_video_media`` / ``_video_suffix`` (семантика байт-в-байт);
* ``handlers/video_download.py`` — native-first маршрутизация (F14);
* ``services/tool_router.py`` — нативный путь инструментов (F14);
* ``services/direct_chat_service.py`` — эмиссия ``ToolContext.native_media``
  (интерфейсная строка F13 → F14).

R17: модуль логирует только ``chat_id``/``kind``/``bytes`` — никогда
``file_id``/URL/локальные пути.
"""
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Расширения видео-документов (без mime). Паритет с handlers/youtube.py 3.1.1.
VIDEO_DOC_EXTENSIONS: tuple[str, ...] = ("mp4", "webm", "mov", "mkv", "avi")

#: Виды медиа, которые квалифицируются как «видео» (F14).
VIDEO_KINDS: tuple[str, ...] = ("video", "document")

#: Раунд 10.24 (F19, ADR-1024-20 §2.5): голосовые/кружочки — аддитивное
#: расширение резолвера. Их принимает только инструмент ``transcribe_video``
#: (STT); ``summarize_video``/``download_media``/Fast-Track «скачай» остаются
#: строго на ``VIDEO_KINDS``.
AUDIO_KINDS: tuple[str, ...] = ("voice", "video_note")
MEDIA_KINDS: tuple[str, ...] = VIDEO_KINDS + AUDIO_KINDS

_DEFAULT_FETCH_TIMEOUT = 120.0
_SUFFIX_PREFIX = "nm_"


@dataclass(frozen=True)
class NativeMedia:
    """Медиа-носитель: сообщение-источник + aiogram-объект Video/Document.

    ``kind`` ∈ ``{"video", "document", "voice", "video_note"}`` (F14 + F19).
    Поле ``media`` — разрешённый aiogram-объект (bytes берутся только из него,
    не из текста модели)."""

    source: object          # aiogram types.Message (носитель)
    media: object           # aiogram Video | Document | Voice | VideoNote
    kind: str               # "video" | "document" | "voice" | "video_note"


def document_is_video(doc) -> bool:
    """Document → видео: mime ``video/*``; mime пуст/None → расширение
    ``file_name``; mime задан и не ``video/*`` → НЕ видео (mime авторитетнее).

    Семантика байт-в-байт совпадает с прежней ``_document_is_video``
    (``handlers/youtube.py`` / ``handlers/video_download.py``)."""
    mime = str(getattr(doc, "mime_type", "") or "").strip().lower()
    if mime:
        return mime.startswith("video/")
    name = str(getattr(doc, "file_name", "") or "").lower()
    return any(name.endswith("." + ext) for ext in VIDEO_DOC_EXTENSIONS)


def _has_file_id(media) -> bool:
    """Медиа-объект пригоден к fetch: ``file_id`` — непустая строка.

    Защита от MagicMock/битых объектов (как в прежнем
    ``video_download._reply_video_media``)."""
    return isinstance(getattr(media, "file_id", None), str) and bool(
        getattr(media, "file_id", ""))


def resolve_reply_video(message) -> NativeMedia | None:
    """Нативное медиа из сообщения: **своё** (``message``) приоритетнее
    реплая; внутри кандидата порядок ``video`` → видео-``document`` →
    ``voice`` → ``video_note``. Голосовые/кружочки расширены F19 (ADR-1024-20
    §2.5) — их принимает только ``transcribe_video``; Fast-Track «скачай»
    отсекает их по ``VIDEO_KINDS``. Никогда не бросает (F13 вызывает на
    каждом direct_chat-сообщении)."""
    try:
        candidates = (message, getattr(message, "reply_to_message", None))
    except Exception:
        logger.debug("[native_media] message read failed")
        return None
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            video = getattr(candidate, "video", None)
            if video is not None and _has_file_id(video):
                return NativeMedia(source=candidate, media=video, kind="video")
            document = getattr(candidate, "document", None)
            if (document is not None and _has_file_id(document)
                    and document_is_video(document)):
                return NativeMedia(source=candidate, media=document,
                                   kind="document")
            # F19 (ADR-1024-20 §2.5): голосовое/кружок — аддитивно, для STT.
            voice = getattr(candidate, "voice", None)
            if voice is not None and _has_file_id(voice):
                return NativeMedia(source=candidate, media=voice, kind="voice")
            video_note = getattr(candidate, "video_note", None)
            if video_note is not None and _has_file_id(video_note):
                return NativeMedia(source=candidate, media=video_note,
                                   kind="video_note")
        except Exception as exc:
            # R17: только класс исключения (без str/repr/file_id/путей).
            logger.debug("[native_media] media resolve failed — skip | error=%s",
                         type(exc).__name__)
            continue
    return None


def media_suffix(media: NativeMedia) -> str:
    """Суффикс tmp-файла: ``video``/``video_note`` → ``.mp4``; ``voice`` →
    ``.ogg``; ``document`` — по ``file_name`` (известное видео-расширение)
    либо ``.mp4`` по умолчанию."""
    kind = getattr(media, "kind", "")
    if kind == "video" or kind == "video_note":
        return ".mp4"
    if kind == "voice":
        return ".ogg"
    name = str(getattr(getattr(media, "media", None), "file_name", "")
               or "").lower()
    for ext in VIDEO_DOC_EXTENSIONS:
        if name.endswith("." + ext):
            return f".{ext}"
    return ".mp4"


async def download_to_tmp(bot, media: NativeMedia, *,
                          timeout: float = _DEFAULT_FETCH_TIMEOUT) -> Path:
    """Скачать нативное медиа во временный файл (``fetch_media_to_tmp``).

    Возвращает существующий ``Path``; при провале/таймауте tmp-файл удаляется,
    исключение пробрасывается наружу (вызывающий решает, как деградировать).
    R17: в логе только ``kind``/``bytes`` — без ``file_id``/путей."""
    import asyncio

    from services.media_download import fetch_media_to_tmp

    suffix = media_suffix(media)
    fd, tmp_path = tempfile.mkstemp(prefix=_SUFFIX_PREFIX, suffix=suffix)
    os.close(fd)
    try:
        await asyncio.wait_for(
            fetch_media_to_tmp(bot, media.media, tmp_path), timeout=timeout)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    try:
        size = os.path.getsize(tmp_path)
    except OSError:
        size = -1
    logger.info("[native_media] fetched | kind=%s | bytes=%d",
                getattr(media, "kind", "?"), size)
    return Path(tmp_path)
