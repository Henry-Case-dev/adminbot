"""Epic 24 — XML grounding context builder (R6, Section 33.6).

Builds <chat_history><message …/></chat_history> with escaping (saxutils + control
chars stripped), media descriptions, and window caps.
"""
import datetime
import logging
import re
from xml.sax.saxutils import escape as _xml_escape

from config.settings import settings
from services import hot_config as hot
from services.database import row_get
from services.summary_aliases import AliasResolver

logger = logging.getLogger(__name__)

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

_MEDIA_DESCRIPTIONS = {
    "photo": "[фото]",
    "video": "[видео]",
    "voice": "[голосовое]",
    "audio": "[аудио]",
    "animation": "[гифка]",
    "sticker": "[стикер]",
    "document": "[файл]",
    "other": "[медиа]",
}


def _clean_controls(text: str) -> str:
    """Strip non-printable control characters that are illegal in XML 1.0."""
    return _CONTROL_CHARS_RE.sub("", text)


def _escape(text: str, quote: bool = False) -> str:
    cleaned = _clean_controls(text)
    if quote:
        return _xml_escape(cleaned, {'"': "&quot;"})
    return _xml_escape(cleaned)


def escape_xml_text(text: str, quote: bool = False) -> str:
    """Public helper: XML-escape text (saxutils + control chars stripped).

    Used by the generator for <memory>/<facts> blocks so that L2 quotes and
    L3 facts go through the same escaping as <chat_history> (review Low-2).
    """
    return _escape(text, quote=quote)


class XmlGroundingBuilder:
    """Builds the XML chat history block for the LLM prompt."""

    def build(self, messages: list, aliases: AliasResolver | None = None) -> str:
        """messages: rows with id/timestamp/author_name/text/reply_to_id/media_type."""
        if not messages:
            return "<chat_history/>"

        parts = ["<chat_history>"]
        total_chars = 0
        for row in messages[: hot.get("limits.summary_max_window_messages", settings.SUMMARY_MAX_WINDOW_MESSAGES)]:
            element = self._build_element(row, aliases)
            if total_chars + len(element) > hot.get("limits.summary_max_context_chars", settings.SUMMARY_MAX_CONTEXT_CHARS):
                logger.warning(
                    "XML context: hard cap %d chars reached, stopping at %d messages",
                    hot.get("limits.summary_max_context_chars", settings.SUMMARY_MAX_CONTEXT_CHARS), len(parts) - 1,
                )
                break
            parts.append(element)
            total_chars += len(element)
        parts.append("</chat_history>")
        return "\n".join(parts)

    def _build_element(self, row, aliases=None) -> str:
        msg_id = row["id"]
        timestamp = row["timestamp"]
        try:
            iso = datetime.datetime.fromtimestamp(
                int(timestamp), tz=datetime.timezone.utc
            ).isoformat()
        except (TypeError, ValueError, OSError):
            iso = ""
        author = (row["author_name"] or "").strip()
        if aliases is not None:
            # Epic 28 (T-213-D): алиас побеждает устаревший author_name старых строк
            author = aliases.resolve(int(row["user_id"] or 0), author or None, None)
        media_type = row["media_type"] or "text"
        body = self._build_body(row["text"], media_type)
        reply_to_id = row["reply_to_id"]
        reply_attr = "" if reply_to_id is None else str(reply_to_id)
        extra = ""
        if row_get(row, "is_forward"):
            extra += ' is_forward="true"'
            source = (row_get(row, "forward_source") or "").strip()
            if source:
                extra += f' forward_source="{_escape(source, quote=True)}"'
        return (
            f'<message id="{msg_id}" timestamp="{iso}" author="{_escape(author, quote=True)}" '
            f'reply_to_id="{reply_attr}" type="{media_type}"{extra}>{_escape(body)}</message>'
        )

    def _build_body(self, text: str | None, media_type: str) -> str:
        if media_type == "text":
            return (text or "")[: hot.get("limits.summary_max_message_chars", settings.SUMMARY_MAX_MESSAGE_CHARS)]
        description = _MEDIA_DESCRIPTIONS.get(media_type, "[медиа]")
        caption = (text or "").strip()
        # Epic 67 (D267): у транскрибированных voice/video реальный текст уже
        # в smart_messages.text — суффикс-плейсхолдер не добавляем.
        if media_type in ("voice", "video") and caption:
            return caption[: hot.get("limits.summary_max_message_chars", settings.SUMMARY_MAX_MESSAGE_CHARS)]
        if caption:
            caption = caption[: hot.get("limits.summary_max_message_chars", settings.SUMMARY_MAX_MESSAGE_CHARS)]
            return f"{caption} {description}"
        return description
