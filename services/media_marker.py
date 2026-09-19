"""Раунд 10.24 (F13, ADR-1024-14) — медиа-маркер нативного медиа в контексте.

Единый диалект маркера нативного медиа для всех рендеров контекста
(``thread_chain`` / ``chat_context`` / ``<Current_Question>`` direct_chat) и
единственный источник контракта для потребителей (F14 — инструменты).

Формат (single dialect)::

    [медиа: {media_type}]              # реф неизвестен (R16 — опускаем)
    [медиа: {media_type} tg:{id}]      # внутренний реф: Telegram id медиа-узла
    [медиа: {media_type} msg:{id}]     # внутренний реф: внутренний id строки

``{media_type}`` — словарь БД, совпадающий с ``handlers.summary._detect_media_type``
(``video|photo|voice|audio|animation|sticker|document|other``). ``{id}`` —
**внутренний** идентификатор; публичный URL / ``file_id`` / токены в контекст
не попадают (R17). Неизвестный/битый ``media_type`` санитизируется до ``[a-z_]``
(≤20), пусто → ``other`` — инъекция в каноническую строку невозможна.

Regex потребителя (F14)::

    ^\\[медиа: (?P<media>[a-z_]{1,20})(?: (?P<ref>(?:tg|msg):\\d+))?\\]$

Инвариант: при отсутствии медиа рендеры выводят байт-в-байт прежний результат —
маркер появляется только когда строка несёт медиа.
"""
import logging
import re

from config.settings import settings
from services.database import row_get

logger = logging.getLogger(__name__)

# Словарь токенов медиа (паритет с handlers.summary._detect_media_type).
MEDIA_TYPES = frozenset({
    "video", "photo", "voice", "audio",
    "animation", "sticker", "document", "other",
})

_MAX_TYPE_LEN = 20

# Regex маркера — контракт для потребителя (F14 парсит одним regex без
# корреляции с заголовком строки).
MEDIA_MARKER_RE = re.compile(
    r"^\[медиа: (?P<media>[a-z_]{1,20})(?: (?P<ref>(?:tg|msg):\d+))?\]$")

# Внутренний реф: ровно ``tg:<цифры>`` / ``msg:<цифры>`` (без URL/file_id).
_REF_RE = re.compile(r"^(?:tg|msg):\d+$")

# Санитизация типа: только строчные [a-z_] (срезаем переносы/скобки/иное).
_TYPE_STRIP_RE = re.compile(r"[^a-z_]")


def _sanitize_media_type(media_type) -> str:
    """Тип БД/сообщения → безопасный токен ``[a-z_]`` (≤20); пусто → ``other``.

    Никогда не бросает; неизвестное/битое (в т.ч. не-ASCII, скобки, переносы)
    срезается — инъекция в каноническую строку невозможна."""
    if media_type is None:
        return "other"
    try:
        raw = str(media_type)
    except Exception:                       # pragma: no cover — защита от __str__
        return "other"
    token = _TYPE_STRIP_RE.sub("", raw.strip().lower())[:_MAX_TYPE_LEN]
    return token or "other"


def is_media_type(media_type) -> bool:
    """Непустой токен и не ``text`` → True (строки-медиа контекста)."""
    if media_type is None:
        return False
    token = str(media_type).strip().lower()
    return bool(token) and token != "text"


def media_marker(media_type, item_id=None) -> str:
    """Маркер медиа: ``[медиа: {type}]`` (+ `` tg:{id}``/`` msg:{id}`` при рефе).

    ``item_id`` вне формата ``(tg|msg):<цифры>`` (пусто/None/URL) → реф
    опускается (R16/R17). Никогда не бросает."""
    token = _sanitize_media_type(media_type)
    ref = str(item_id or "")
    if ref and _REF_RE.match(ref):
        return f"[медиа: {token} {ref}]"
    return f"[медиа: {token}]"


def row_media_marker(row, item_id=None) -> str:
    """Маркер строки ``smart_messages`` по колонке ``media_type`` (row_get).

    Нет медиа/``text``/пусто → ``""`` (вызывающий сохраняет прежний скип —
    байт-в-байт). Никогда не бросает."""
    try:
        media_type = row_get(row, "media_type")
    except Exception:
        logger.debug("media_marker: media_type read failed", exc_info=True)
        return ""
    if not is_media_type(media_type):
        return ""
    return media_marker(media_type, item_id)


def message_media_type(message) -> str | None:
    """aiogram-like сообщение → токен медиа БД (или ``None`` для текста/пусто).

    Словарь совпадает с ``_detect_media_type`` (``handlers.summary``):
    ``video``/``video_note`` → ``"video"``, далее photo/voice/audio/animation/
    sticker/document. Текст присутствует → ``None`` (медиа нет). Никогда не
    бросает."""
    if message is None:
        return None
    try:
        # Текст (или его отсутствие) — признак отсутствия нативного медиа.
        if getattr(message, "text", None) is not None:
            return None
        if (getattr(message, "video", None) is not None
                or getattr(message, "video_note", None) is not None):
            return "video"
        if getattr(message, "photo", None) is not None:
            return "photo"
        if getattr(message, "voice", None) is not None:
            return "voice"
        if getattr(message, "audio", None) is not None:
            return "audio"
        if getattr(message, "animation", None) is not None:
            return "animation"
        if getattr(message, "sticker", None) is not None:
            return "sticker"
        if getattr(message, "document", None) is not None:
            return "document"
    except Exception:
        logger.debug("media_marker: message media resolve failed",
                     exc_info=True)
        return None
    return None


def media_context_enabled() -> bool:
    """env-only kill-switch ``NATIVE_REPLY_MEDIA_CONTEXT_ENABLED`` (default ON).

    Единая точка чтения флага для всех рендеров и тестов. OFF → медиа-строки
    снова скипаются (байт-в-байт прежнее поведение)."""
    return bool(getattr(settings, "NATIVE_REPLY_MEDIA_CONTEXT_ENABLED", True))
