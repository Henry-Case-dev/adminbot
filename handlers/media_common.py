"""Bugfix 04.09.2026 (Часть 1) — чистые хелперы автора/факта транскриптов.

Перенос из handlers/voice_transcription.py (Epic 72, Section 74.B/D272/D273)
БЕЗ изменения поведения. Потребители: voice_transcription (реэкспорт теми же
именами), youtube.py (нативные видео, Часть 1).

DI алиасов: handlers.media_common._aliases заполняется из setup-функций
хендлеров (voice_transcription / youtube), которые получают единый
AliasResolver из bot.py on_startup.
"""
import html
from datetime import datetime, timezone

from aiogram import types

from handlers.summary import _extract_forward_source

# Каскад AliasResolver (Алиас → Никнейм → Юзернейм → ID) для не-форвардов.
_aliases = None

MEDIA_UNKNOWN_AUTHOR = "Неизвестный"   # Epic 72 (74.B/D272): константа автора


def set_media_aliases(aliases) -> None:
    """DI: AliasResolver для каскада _resolve_transcript_author (не-форварды)."""
    global _aliases
    _aliases = aliases


def _build_nickname(user) -> str | None:
    """Прецедент handlers/summary.py:137 — first_name+last_name."""
    parts = []
    for attr in ("first_name", "last_name"):
        value = getattr(user, attr, None)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return " ".join(parts) if parts else None


def _resolve_transcript_author(message: types.Message) -> str:
    """Epic 72 (74.B.1, D272): автор для лейбла расшифровки.
    Форвард → каскад _extract_forward_source (handlers/summary.py,
    прецедент импорта handler→handler: handlers/factcheck.py:21):
    MessageOriginUser → AliasResolver (Алиас→Никнейм→Юзернейм без @),
    HiddenUser → sender_user_name, Channel/Chat → title (+@username).
    Извлечение не удалось (exotic-тип/битый origin) → «Неизвестный»
    (MEDIA_UNKNOWN_AUTHOR; summary/observer НЕ затронуты).
    Не-форвард → прежний каскад от from_user (D268-поведение)."""
    origin = getattr(message, "forward_origin", None)
    if origin is not None:
        return (_extract_forward_source(origin) or MEDIA_UNKNOWN_AUTHOR)
    user = message.from_user
    if _aliases is None:
        return _build_nickname(user) or MEDIA_UNKNOWN_AUTHOR
    return _aliases.resolve(
        user.id,
        nickname=_build_nickname(user),
        username=getattr(user, "username", None),
    )


def wrap_media_fact(media_type: str, sender: str, text: str,
                    forward_source: str | None = None) -> str:
    """Обёртка транскрипта для GraphRAG-экстрактора (D267):
    '<MediaMessage type="voice" sender="..." timestamp="<ISO8601 UTC>">...</MediaMessage>'.
    Epic 72 (74.B.3, D273): у форвардов добавляются атрибуты
    forwarded="true" forward_from="{автор источника}" (html.escape quote=True —
    ОВ-3: XML-совместимо и консистентно с D268; ОВ-3 решён в пользу html.escape).
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    extra = ""
    if forward_source:
        extra = (f' forwarded="true"'
                 f' forward_from="{html.escape(forward_source, quote=True)}"')
    return (f'<MediaMessage type="{media_type}" sender="{sender}" '
            f'timestamp="{timestamp}"{extra}>{text}</MediaMessage>')
