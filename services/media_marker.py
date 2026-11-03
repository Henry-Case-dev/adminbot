"""Раунд 10.24 (F13, ADR-1024-14) — медиа-маркер нативного медиа в контексте.

Единый диалект маркера нативного медиа для всех рендеров контекста
(``thread_chain`` / ``chat_context`` / ``<Current_Question>`` direct_chat) и
единственный источник контракта для потребителей (F14 — инструменты).

Формат (single dialect)::

    [медиа: {media_type}]              # реф неизвестен (R16 — опускаем)
    [медиа: {media_type} {ref}]        # внутренний реф: tg:<id> / msg:<id>
    [медиа: {media_type} {label}]      # речевая проекция: M<n> (EVOL v5 §4.2)

``{media_type}`` — словарь БД, совпадающий с ``handlers.summary._detect_media_type``
(``video|photo|voice|audio|animation|sticker|document|other``). ``{id}`` —
**внутренний** идентификатор; публичный URL / ``file_id`` / токены в контекст
не попадают (R17). Неизвестный/битый ``media_type`` санитизируется до ``[a-z_]``
(≤20), пусто → ``other`` — инъекция в каноническую строку невозможна.

EVOL-REPLY-CONTEXT-INTEGRITY-01 v5 (§4.2 п.2): медиа-узел — та же строка
контекста, поэтому в РЕЧЕВОЙ проекции его ref заменяется меткой прогона
(``[медиа: video M7]``) либо опускается, если рефа нет. Сырой вид
(``tg:``/``msg:``) остаётся дефолтом — он нужен машинной стороне и
откату (``flags.context_speech_projection`` OFF).

Regex потребителя (F14)::

    ^\\[медиа: (?P<media>[a-z_]{1,20})(?: (?P<ref>(?:tg|msg):\\d+|[MFU]\\d+))?\\]$

Инвариант: при отсутствии медиа рендеры выводят байт-в-байт прежний результат —
маркер появляется только когда строка несёт медиа.
"""
import logging
import re

from config.settings import settings
from services.canonical_context import SPEECH_LABEL_RE, speech_projection_enabled
from services.database import row_get

logger = logging.getLogger(__name__)

# Словарь токенов медиа (паритет с handlers.summary._detect_media_type).
MEDIA_TYPES = frozenset({
    "video", "photo", "voice", "audio",
    "animation", "sticker", "document", "other",
})

_MAX_TYPE_LEN = 20

# Regex маркера — контракт для потребителя (F14 парсит одним regex без
# корреляции с заголовком строки). Речевая метка (`M7`) — валидный ref наряду
# с внутренним (`tg:123`/`msg:9`).
MEDIA_MARKER_RE = re.compile(
    r"^\[медиа: (?P<media>[a-z_]{1,20})"
    r"(?: (?P<ref>(?:tg|msg):\d+|[MFU]\d+))?\]$")

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


def _speech_label(projection, item_id, label):
    """Речевая метка медиа-узла или ``None``, если речевой вид не активен.

    ``None`` → маркер остаётся с внутренним ref (сырой вид / откат).
    ``""`` → речевой вид без рефа (метки нет — узел без адресуемого id)."""
    explicit = str(label or "").strip()
    if explicit:
        return explicit if SPEECH_LABEL_RE.match(explicit) else None
    if projection is None:
        return None
    try:
        if not speech_projection_enabled():
            return None
    except Exception:                       # pragma: no cover — шов недоступен
        logger.debug("media_marker: speech flag unavailable", exc_info=True)
        return None
    return projection.message_label(item_id) or ""


def media_marker(media_type, item_id=None, *, projection=None,
                 label=None) -> str:
    """Маркер медиа: ``[медиа: {type}]`` (+ ref при наличии).

    Сырой вид (дефолт): `` tg:{id}``/`` msg:{id}`` — внутренний идентификатор
    медиа-узла. Речевой вид (``projection`` либо явный ``label``): метка
    прогона ``M7`` вместо внутреннего ref — при активном
    ``flags.context_speech_projection``. ``item_id`` вне формата
    ``(tg|msg):<цифры>`` (пусто/None/URL) → реф опускается (R16/R17).
    Никогда не бросает."""
    token = _sanitize_media_type(media_type)
    speech = _speech_label(projection, item_id, label)
    if speech is not None:
        return f"[медиа: {token} {speech}]" if speech else f"[медиа: {token}]"
    ref = str(item_id or "")
    if ref and _REF_RE.match(ref):
        return f"[медиа: {token} {ref}]"
    return f"[медиа: {token}]"


def row_media_marker(row, item_id=None, *, projection=None) -> str:
    """Маркер строки ``smart_messages`` по колонке ``media_type`` (row_get).

    Нет медиа/``text``/пусто → ``""`` (вызывающий сохраняет прежний скип —
    байт-в-байт). ``projection`` → речевая метка вместо внутреннего ref.
    Никогда не бросает."""
    try:
        media_type = row_get(row, "media_type")
    except Exception:
        logger.debug("media_marker: media_type read failed", exc_info=True)
        return ""
    if not is_media_type(media_type):
        return ""
    return media_marker(media_type, item_id, projection=projection)


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
