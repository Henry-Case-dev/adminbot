"""P0-HC C1 — безопасный Telegram-egress для структурных ответов Direct.

Модуль добавляет **закрытый** парсер узкого Markdown-подмножества и
преобразование в поддерживаемый Telegram HTML. Никакого raw-HTML-passthrough
нет: всё, что не распознано как собственный спан, экранируется.

Публичный контракт (см. arch-contract-2026-11-21 §4.1):

``decide_markup(text) -> (mode, reason)``
    ``plain`` — байт-паритет с текущей plain-доставкой; ``telegram_html`` —
    структурная разметка, которую можно отдать с ``parse_mode="HTML"``.

``render_telegram_html(text) -> str``
    Тот же смысл в Telegram HTML (закрытые теги, экранированные спецсимволы).

``render_plain(text) -> str``
    Тот же смысл без маркеров разметки (ссылки сохраняются текстом).

``split_telegram_html(html, limit) -> list[str]``
    Тег-безопасные чанки по UTF-16 code units: открытые теги закрываются в
    конце чанка и переоткрываются в начале следующего, включительно ``<a>``
    с тем же ``href``; разрыв не попадает внутрь тега/entity.

``send_structured(...) -> int | None``
    Отправка через существующие ``telegram_send.send_text`` /
    ``send_chunked_reply``; HTML-fallback только для сбойного чанка, без
    повторной отправки уже доставленных и без новой LLM-генерации.
"""
from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from typing import Any, Iterable

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from config.settings import settings
from services import hot_config as hot
from services.outgoing_guard import sanitize_outgoing
from services.smartmodule_utils import _CHUNK_LIMIT, send_chunked_reply
from services.telegram_send import send_text

logger = logging.getLogger(__name__)

# Единственный источник лимита — существующий SmartModule-лимит Telegram.
DEFAULT_CHUNK_LIMIT = _CHUNK_LIMIT

_ALLOWED_TAGS = frozenset({"b", "i", "u", "s", "code", "pre", "blockquote", "a"})
_SAFE_URL_PREFIXES = ("http://", "https://", "tg://")
_ESCAPABLE = frozenset(r"""!"#$%&'()*+,-./:;<=>?@[\]^_`{|}~\"""")
_MAX_INLINE_DEPTH = 8

_LINK_RE = re.compile(r"\[([^\[\]\n]{1,300})\]\(([^()\s<>\"']{1,2048})\)")
_FENCE_OPEN_RE = re.compile(r"^[ \t]{0,3}```+[ \t]*([^\s`]{0,32})[ \t]*$")
_FENCE_CLOSE_RE = re.compile(r"^[ \t]{0,3}```+[ \t]*$")
_HEADING_RE = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_QUOTE_RE = re.compile(r"^[ \t]{0,3}>[ \t]?(.*)$")
_UL_RE = re.compile(r"^[ \t]{0,3}[-*+][ \t]+(.+?)[ \t]*$")
_OL_RE = re.compile(r"^[ \t]{0,3}(\d{1,9})[.)][ \t]+(.+?)[ \t]*$")
_PSEUDO_BOLD_RE = re.compile(r"\*\*(?!\s)(.+?)(?<!\s)\*\*")
_PSEUDO_UNDERSCORE_RE = re.compile(r"__(?!\s)(.+?)(?<!\s)__")
_TAG_RE = re.compile(r"<[^>]{1,8192}>")
_TAG_NAME_RE = re.compile(r"</?\s*([a-zA-Z][a-zA-Z0-9-]*)")
_ENTITY_RE = re.compile(
    r"&(?:amp|lt|gt|quot|#\d{1,6}|#x[0-9a-fA-F]{1,6});")
_HTML_TAG_STRIP_RE = re.compile(r"</?(?:b|i|u|s|code|pre|blockquote|a)\b[^>]*>")
_HTML_LINK_RE = re.compile(r'<a href="([^"]*)">(.*?)</a>', re.DOTALL)
_LANGUAGE_RE = re.compile(r"^[A-Za-z0-9_+.-]{1,32}$")

# Inline-узлы: ("text", str) | ("bold"|"italic"|"strike", nodes) |
# ("code", str) | ("link", nodes, url).
InlineNode = tuple[Any, ...]
Block = tuple[Any, ...]


# ── escaping и UTF-16 ───────────────────────────────────────────────────────

def _escape_html(value: str) -> str:
    """Телеграм-экранирование: только поддерживаемые им сущности.

    ``html.escape(quote=True)`` добавил бы ``&#x27;``, а Telegram не
    поддерживает числовые entity. Одинарная кавычка в тексте безопасна.
    """
    return (str(value).replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def utf16_units(text: str) -> int:
    """Длина строки в UTF-16 code units (лимит Telegram 4096).

    Для одиночного surrogate Python-строка не кодируется — считаем его
    одним unit, чтобы функция оставалась тотальной.
    """
    source = str(text)
    try:
        return len(source.encode("utf-16-le")) // 2
    except UnicodeEncodeError:          # lone surrogate — defensive
        return sum(2 if ord(ch) > 0xFFFF else 1 for ch in source)


# ── inline-парсер ──────────────────────────────────────────────────────────

def _is_word_char(ch: str) -> bool:
    return bool(ch) and (ch.isalnum() or ch == "_")


def _can_open_underscore(text: str, index: int, width: int) -> bool:
    previous = text[index - 1] if index > 0 else ""
    following = text[index + width] if index + width < len(text) else ""
    if _is_word_char(previous):
        return False
    if not following or following.isspace():
        return False
    return True


def _find_bold_close(text: str, start: int, delim: str) -> int:
    position = start
    while True:
        found = text.find(delim, position)
        if found < 0:
            return -1
        content = text[start:found]
        if "\n" in content:
            return -1
        if not content or content[0].isspace() or content[-1].isspace():
            position = found + len(delim)
            continue
        if delim == "__" and found + 2 < len(text) and _is_word_char(text[found + 2]):
            position = found + 2
            continue
        return found


def _find_italic_close(text: str, start: int, delim: str) -> int:
    position = start
    while True:
        found = text.find(delim, position)
        if found < 0:
            return -1
        if "\n" in text[start:found]:
            return -1
        if found == start or text[found - 1].isspace():
            position = found + 1
            continue
        if text.startswith(delim * 2, found):
            position = found + 1
            continue
        if found > 0 and text[found - 1] == delim:
            position = found + 1
            continue
        if delim == "_" and found + 1 < len(text) and _is_word_char(text[found + 1]):
            position = found + 1
            continue
        return found


def _safe_url(url: str) -> bool:
    source = str(url or "").strip()
    lowered = source.lower()
    if not lowered.startswith(_SAFE_URL_PREFIXES):
        return False
    if any(ch in source for ch in " \t\r\n<>\"'"):
        return False
    if lowered.startswith(("http://", "https://")):
        host = source.split("://", 1)[1]
        return bool(host) and not host.startswith("/")
    return len(source) > len("tg://")


def _parse_inline(text: str, *, tier: int, depth: int = 0) -> list[InlineNode]:
    """Закрытый inline-парсер; непонятые маркеры остаются текстом."""
    if depth > _MAX_INLINE_DEPTH:
        return [("text", text)]

    nodes: list[InlineNode] = []
    buffer: list[str] = []
    index = 0
    length = len(text)

    def flush() -> None:
        if buffer:
            nodes.append(("text", "".join(buffer)))
            buffer.clear()

    while index < length:
        char = text[index]

        if char == "\\" and index + 1 < length and text[index + 1] in _ESCAPABLE:
            buffer.append(text[index + 1])
            index += 2
            continue

        if char == "`":
            closing = text.find("`", index + 1)
            if (closing > index + 1
                    and "\n" not in text[index + 1:closing]):
                flush()
                nodes.append(("code", text[index + 1:closing]))
                index = closing + 1
                continue
            buffer.append(char)
            index += 1
            continue

        if char == "[":
            match = _LINK_RE.match(text, index)
            if match is not None and _safe_url(match.group(2)):
                flush()
                label = _parse_inline(
                    match.group(1), tier=tier, depth=depth + 1)
                nodes.append(("link", label, match.group(2)))
                index = match.end()
                continue
            buffer.append(char)
            index += 1
            continue

        if text.startswith("**", index):
            closing = _find_bold_close(text, index + 2, "**")
            if closing >= 0:
                flush()
                nodes.append((
                    "bold",
                    _parse_inline(
                        text[index + 2:closing], tier=tier, depth=depth + 1),
                ))
                index = closing + 2
                continue
            buffer.append("**")
            index += 2
            continue

        if text.startswith("__", index):
            closing = (-1 if not _can_open_underscore(text, index, 2)
                       else _find_bold_close(text, index + 2, "__"))
            if closing >= 0:
                flush()
                nodes.append((
                    "bold",
                    _parse_inline(
                        text[index + 2:closing], tier=tier, depth=depth + 1),
                ))
                index = closing + 2
                continue
            buffer.append("__")
            index += 2
            continue

        if text.startswith("~~", index):
            closing = _find_bold_close(text, index + 2, "~~")
            if tier >= 2 and closing >= 0:
                flush()
                nodes.append((
                    "strike",
                    _parse_inline(
                        text[index + 2:closing], tier=tier, depth=depth + 1),
                ))
                index = closing + 2
                continue
            buffer.append("~~")
            index += 2
            continue

        if char in "*_" and tier >= 2:
            allowed = (char != "_"
                       or _can_open_underscore(text, index, 1))
            closing = (-1 if not allowed
                       else _find_italic_close(text, index + 1, char))
            if closing >= 0:
                flush()
                nodes.append((
                    "italic",
                    _parse_inline(
                        text[index + 1:closing], tier=tier, depth=depth + 1),
                ))
                index = closing + 1
                continue
            buffer.append(char)
            index += 1
            continue

        buffer.append(char)
        index += 1

    flush()
    return nodes


def _walk_nodes(nodes: Iterable[InlineNode]) -> Iterable[InlineNode]:
    for node in nodes:
        yield node
        if node[0] in ("bold", "italic", "strike"):
            yield from _walk_nodes(node[1])
        elif node[0] == "link":
            yield from _walk_nodes(node[1])


def _render_nodes(nodes: Iterable[InlineNode], mode: str) -> str:
    parts: list[str] = []
    for node in nodes:
        kind = node[0]
        if kind == "text":
            parts.append(_escape_html(node[1]) if mode == "html" else node[1])
        elif kind in ("bold", "italic", "strike"):
            inner = _render_nodes(node[1], mode)
            if mode == "html":
                tag = {"bold": "b", "italic": "i", "strike": "s"}[kind]
                parts.append(f"<{tag}>{inner}</{tag}>")
            else:
                parts.append(inner)
        elif kind == "code":
            parts.append(
                f"<code>{_escape_html(node[1])}</code>"
                if mode == "html" else node[1])
        elif kind == "link":
            label_nodes, url = node[1], node[2]
            if mode == "html":
                parts.append(
                    f'<a href="{_escape_html(url)}">'
                    f'{_render_nodes(label_nodes, "html")}</a>')
            else:
                label = _render_nodes(label_nodes, "plain")
                parts.append(url if label.strip() == url
                             else f"{label} ({url})")
        else:                              # pragma: no cover - defensive
            parts.append(_escape_html(str(node[1]))
                         if mode == "html" else str(node[1]))
    return "".join(parts)


# ── блочный парсер ────────────────────────────────────────────────────────

def _pseudo_heading(line: str) -> str | None:
    stripped = line.strip()
    for pattern in (_PSEUDO_BOLD_RE, _PSEUDO_UNDERSCORE_RE):
        if pattern.fullmatch(stripped):
            return pattern.fullmatch(stripped).group(1)
    return None


def _is_block_start(line: str) -> bool:
    return bool(
        _FENCE_OPEN_RE.match(line)
        or _HEADING_RE.match(line)
        or _QUOTE_RE.match(line)
        or _UL_RE.match(line)
        or _OL_RE.match(line)
        or _pseudo_heading(line) is not None
    )


def _parse_blocks(text: str) -> list[Block]:
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    blocks: list[Block] = []
    index = 0

    while index < len(lines):
        line = lines[index]

        if not line.strip():
            blocks.append(("blank",))
            index += 1
            continue

        fence = _FENCE_OPEN_RE.match(line)
        if fence is not None:
            language = fence.group(1)
            index += 1
            code_lines: list[str] = []
            while index < len(lines) and not _FENCE_CLOSE_RE.match(lines[index]):
                code_lines.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            blocks.append(("fence", language, "\n".join(code_lines)))
            continue

        heading = _HEADING_RE.match(line)
        if heading is not None:
            blocks.append(
                ("heading", len(heading.group(1)), heading.group(2).strip()))
            index += 1
            continue

        pseudo = _pseudo_heading(line)
        if pseudo is not None:
            blocks.append(("heading", 0, pseudo))
            index += 1
            continue

        if _QUOTE_RE.match(line):
            quoted: list[str] = []
            while index < len(lines) and _QUOTE_RE.match(lines[index]):
                quoted.append(_QUOTE_RE.match(lines[index]).group(1))
                index += 1
            blocks.append(("quote", quoted))
            continue

        if _UL_RE.match(line):
            bullets: list[str] = []
            while index < len(lines) and _UL_RE.match(lines[index]):
                bullets.append(_UL_RE.match(lines[index]).group(1))
                index += 1
            blocks.append(("ul", bullets))
            continue

        if _OL_RE.match(line):
            ordered: list[tuple[str, str]] = []
            while index < len(lines) and _OL_RE.match(lines[index]):
                match = _OL_RE.match(lines[index])
                ordered.append((match.group(1), match.group(2)))
                index += 1
            blocks.append(("ol", ordered))
            continue

        paragraph = [line]
        index += 1
        while (index < len(lines) and lines[index].strip()
               and not _is_block_start(lines[index])):
            paragraph.append(lines[index])
            index += 1
        blocks.append(("paragraph", paragraph))

    return blocks


def _render_blocks(blocks: Iterable[Block], *, mode: str, tier: int) -> str:
    parts: list[str] = []
    for block in blocks:
        kind = block[0]
        if kind == "blank":
            parts.append("")
        elif kind == "paragraph":
            parts.append("\n".join(
                _render_nodes(_parse_inline(line, tier=tier), mode)
                for line in block[1]))
        elif kind == "fence":
            language, code = block[1], block[2]
            if mode == "html":
                language_class = (
                    f' class="language-{_escape_html(language)}"'
                    if _LANGUAGE_RE.match(language) else "")
                parts.append(
                    f"<pre><code{language_class}>"
                    f"{_escape_html(code)}</code></pre>")
            else:
                parts.append(code)
        elif kind == "heading":
            inner = _render_nodes(_parse_inline(block[2], tier=tier), mode)
            parts.append(f"<b>{inner}</b>" if mode == "html" else inner)
        elif kind == "quote":
            inner = "\n".join(
                _render_nodes(_parse_inline(line, tier=tier), mode)
                for line in block[1])
            parts.append(
                f"<blockquote>{inner}</blockquote>"
                if mode == "html" else inner)
        elif kind == "ul":
            for item in block[1]:
                inner = _render_nodes(_parse_inline(item, tier=tier), mode)
                parts.append(f"• {inner}")
        elif kind == "ol":
            for number, item in block[1]:
                inner = _render_nodes(_parse_inline(item, tier=tier), mode)
                parts.append(f"{number}. {inner}")
        else:                              # pragma: no cover - defensive
            parts.append(str(block[1]) if len(block) > 1 else "")
    return "\n".join(parts)


# ── решение о канале ──────────────────────────────────────────────────────

def _tier_for(source: str) -> tuple[int, str]:
    if not source.strip():
        return 0, "plain_empty"

    blocks = _parse_blocks(source)
    block_tier_two = any(
        block[0] in ("fence", "heading", "quote", "ul", "ol")
        for block in blocks)
    has_tier_one = False
    has_strike = False

    def inspect(nodes: Iterable[InlineNode]) -> None:
        nonlocal has_tier_one, has_strike
        for node in _walk_nodes(nodes):
            if node[0] in ("bold", "code", "link"):
                has_tier_one = True
            elif node[0] == "strike":
                has_strike = True

    for block in blocks:
        if block[0] == "paragraph":
            for line in block[1]:
                inspect(_parse_inline(line, tier=2))
        elif block[0] == "heading":
            inspect(_parse_inline(block[2], tier=2))
        elif block[0] == "quote":
            for line in block[1]:
                inspect(_parse_inline(line, tier=2))
        elif block[0] == "ul":
            for item in block[1]:
                inspect(_parse_inline(item, tier=2))
        elif block[0] == "ol":
            for _, item in block[1]:
                inspect(_parse_inline(item, tier=2))

    if block_tier_two or has_strike:
        return 2, "markup_tier2"
    if has_tier_one:
        return 1, "markup_tier1"
    return 0, "plain_no_markup"


def decide_markup(text: str) -> tuple[str, str]:
    """Выбрать канал по содержанию, а не по длине/эвристике свежести.

    ``plain`` — болтовня, одиночные/экранированные ``*``/``_``; ``html`` —
    только если распознан хотя бы один закрытый поддерживаемый спан.
    """
    tier, reason = _tier_for(str(text or ""))
    return ("plain" if tier == 0 else "telegram_html"), reason


def render_telegram_html(text: str) -> str:
    """Markdown-подмножество → Telegram HTML; всё прочее экранируется."""
    source = str(text or "")
    tier, _ = _tier_for(source)
    return _render_blocks(_parse_blocks(source), mode="html", tier=tier)


def render_plain(text: str) -> str:
    """Тот же смысл без маркеров; plain-текст проходит без изменений."""
    source = str(text or "")
    tier, _ = _tier_for(source)
    return _render_blocks(_parse_blocks(source), mode="plain", tier=tier)


# Совместимые имена из постановки C1.
def to_telegram_html(text: str) -> str:
    return render_telegram_html(text)


def to_plain(text: str) -> str:
    return render_plain(text)


# ── tag-safe chunking ─────────────────────────────────────────────────────

def _cluster_end(source: str, index: int) -> int:
    """Границы grapheme-кластера, который нельзя рвать между code units."""
    end = index + 1
    while end < len(source):
        previous = source[end - 1]
        current = source[end]
        if (unicodedata.combining(current)
                or current in ("\ufe0e", "\ufe0f")
                or 0x1F3FB <= ord(current) <= 0x1F3FF
                or previous == "\u200d"
                or current == "\u200d"):
            end += 1
            continue
        if (0x1F1E6 <= ord(previous) <= 0x1F1FF
                and 0x1F1E6 <= ord(current) <= 0x1F1FF):
            end += 1
            continue
        break
    return end


def _tokenize_html(html: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    index = 0
    while index < len(html):
        if html[index] == "<":
            match = _TAG_RE.match(html, index)
            if match is not None:
                raw = match.group(0)
                name = _TAG_NAME_RE.match(raw)
                tag = (name.group(1).lower() if name is not None else "")
                if tag in _ALLOWED_TAGS:
                    tokens.append(("tag", raw))
                else:
                    tokens.append(("text", raw))
                index = match.end()
                continue
        if html[index] == "&":
            match = _ENTITY_RE.match(html, index)
            if match is not None:
                tokens.append(("entity", match.group(0)))
                index = match.end()
                continue
        end = _cluster_end(html, index)
        tokens.append(("text", html[index:end]))
        index = end
    return tokens


def _tag_kind(raw: str) -> tuple[str, str]:
    name = _TAG_NAME_RE.match(raw)
    if name is None:
        return "text", ""
    tag = name.group(1).lower()
    if raw.startswith("</"):
        return "close", tag
    if raw.rstrip().endswith("/>"):
        return "self", tag
    return "open", tag


def _stack_states(
        tokens: Iterable[tuple[str, str]]) -> list[tuple[tuple[str, str], ...]]:
    states: list[tuple[tuple[str, str], ...]] = [()]
    for kind, raw in tokens:
        stack = states[-1]
        if kind == "tag":
            tag_kind, name = _tag_kind(raw)
            if tag_kind == "open":
                stack = stack + ((name, raw),)
            elif (tag_kind == "close" and stack
                  and stack[-1][0] == name):
                stack = stack[:-1]
        states.append(stack)
    return states


def _reopen_tags(stack: tuple[tuple[str, str], ...]) -> str:
    return "".join(raw for _, raw in stack)


def _close_tags(stack: tuple[tuple[str, str], ...]) -> str:
    return "".join(f"</{name}>" for name, _ in reversed(stack))


def split_telegram_html(html: str,
                        limit: int = DEFAULT_CHUNK_LIMIT) -> list[str]:
    """Разбить Telegram HTML на чанки ≤ ``limit`` UTF-16 units.

    Теги и entity атомарны; открытые теги закрываются в конце каждого чанка
    и переоткрываются в начале следующего (``<a>`` — с тем же ``href``).
    Предпочтительный разрыв — после whitespace, иначе принудительный по
    code-point/cluster-границе.
    """
    source = str(html or "")
    if not source:
        return []
    if limit is None or int(limit) <= 0:
        raise ValueError("limit must be positive")
    limit = int(limit)

    tokens = _tokenize_html(source)
    if not tokens:
        return []
    states = _stack_states(tokens)
    units = [utf16_units(raw) for _, raw in tokens]
    total = len(tokens)
    chunks: list[str] = []
    start = 0

    while start < total:
        prefix = _reopen_tags(states[start])
        prefix_units = utf16_units(prefix)
        body_units = 0
        last_valid = -1
        last_break = -1
        cursor = start

        while cursor < total:
            body_units += units[cursor]
            fits = (prefix_units + body_units
                    + utf16_units(_close_tags(states[cursor + 1])) <= limit)
            if fits:
                last_valid = cursor
                if (tokens[cursor][0] == "text"
                        and tokens[cursor][1].isspace()):
                    last_break = cursor
                cursor += 1
                continue
            if prefix_units + body_units > limit:
                break
            cursor += 1

        if last_valid < start:
            # Лимит меньше одного атомарного тега: не теряем содержимое.
            last_valid = start

        cut = last_valid
        if last_valid < total - 1 and start <= last_break <= last_valid:
            cut = last_break

        chunk = (prefix
                 + "".join(raw for _, raw in tokens[start:cut + 1])
                 + _close_tags(states[cut + 1]))
        chunks.append(chunk)
        start = cut + 1

    return chunks


def html_to_plain(html: str) -> str:
    """Снять только собственные теги модуля; entity раскрыть для fallback.

    Ссылка сохраняется как ``label (url)`` — fallback не должен терять URL.
    """
    import html as _html_module

    def _link_to_plain(match: re.Match[str]) -> str:
        label = match.group(2)
        url = _html_module.unescape(match.group(1))
        return url if label.strip() == url else f"{label} ({url})"

    source = _HTML_LINK_RE.sub(_link_to_plain, str(html or ""))
    return _html_module.unescape(_HTML_TAG_STRIP_RE.sub("", source))


# ── отправка ──────────────────────────────────────────────────────────────

def _reply_target_gone(exc: Exception) -> bool:
    return "message to be replied not found" in str(exc).lower()


async def _send_html_once(bot, chat_id: int, text: str,
                          reply_to: int | None):
    kwargs: dict[str, Any] = {"parse_mode": "HTML"}
    if reply_to:
        kwargs["reply_to_message_id"] = reply_to
    try:
        return await send_text(bot, chat_id, text, **kwargs)
    except TelegramBadRequest as exc:
        if reply_to and _reply_target_gone(exc):
            kwargs.pop("reply_to_message_id", None)
            return await send_text(bot, chat_id, text, **kwargs)
        raise


async def _send_plain_once(bot, chat_id: int, text: str,
                           reply_to: int | None):
    kwargs: dict[str, Any] = {}
    if reply_to:
        kwargs["reply_to_message_id"] = reply_to
    try:
        return await send_text(bot, chat_id, text, **kwargs)
    except TelegramBadRequest as exc:
        if reply_to and _reply_target_gone(exc):
            kwargs.pop("reply_to_message_id", None)
            return await send_text(bot, chat_id, text, **kwargs)
        raise


async def _with_retry_after(sender, *args):
    try:
        return await sender(*args)
    except TelegramRetryAfter as exc:
        logger.warning(
            "telegram_markup: retry_after=%.1fs — one retry | chat_id=%s",
            exc.retry_after, args[1])
        await asyncio.sleep(exc.retry_after)
        return await sender(*args)


async def send_structured(bot, chat_id: int, text: str = "",
                          reply_to: int | None = None, *,
                          document=None,
                          limit: int = DEFAULT_CHUNK_LIMIT) -> int | None:
    """Отправить структурный ответ; plain-путь делегируется SmartModule.

    ``document`` (ResponseDocument) имеет приоритет: используется
    ``document.plain_text()``. HTML-fallback — только для сбойного чанка;
    уже доставленные чанки не переотправляются, LLM не вызывается.
    """
    source = (str(document.plain_text() or "")
              if document is not None else str(text or ""))
    source = sanitize_outgoing(source)
    if not source.strip():
        return None

    mode, reason = decide_markup(source)
    if mode == "plain":
        logger.debug("telegram_markup: plain path | reason=%s", reason)
        # Обычный текст остаётся байт-в-байт; снимаются только escape-маркеры
        # намеренно буквальной разметки.
        return await send_chunked_reply(
            bot, chat_id, render_plain(source), reply_to)

    html = render_telegram_html(source)
    chunks = [chunk for chunk in split_telegram_html(html, limit)
              if chunk.strip()]
    if not chunks:
        return None

    delay = float(hot.get("limits.summary_chunk_delay",
                          settings.SUMMARY_CHUNK_DELAY) or 0)
    sent_id = None

    for index, chunk in enumerate(chunks):
        reply_id = reply_to if index == 0 else None
        try:
            sent = await _with_retry_after(
                _send_html_once, bot, chat_id, chunk, reply_id)
        except TelegramBadRequest as exc:
            logger.warning(
                "telegram_markup: HTML chunk rejected — plain fallback | "
                "chat_id=%s chunk=%d reason=%s",
                chat_id, index, str(exc)[:120])
            try:
                sent = await _with_retry_after(
                    _send_plain_once, bot, chat_id,
                    html_to_plain(chunk), reply_id)
            except TelegramBadRequest as fallback_exc:
                logger.error(
                    "telegram_markup: plain fallback failed — stop | "
                    "chat_id=%s chunk=%d reason=%s",
                    chat_id, index, str(fallback_exc)[:120])
                break
        if (sent is not None
                and getattr(sent, "message_id", None) is not None
                and sent_id is None):
            sent_id = sent.message_id
        if index < len(chunks) - 1:
            await asyncio.sleep(delay)

    return sent_id


def to_telegram_chunks(text: str,
                       limit: int = DEFAULT_CHUNK_LIMIT) -> list[str]:
    """Удобная пара к ``to_telegram_html`` для тестов/диагностики."""
    return split_telegram_html(render_telegram_html(text), limit)


__all__ = [
    "DEFAULT_CHUNK_LIMIT",
    "decide_markup",
    "html_to_plain",
    "render_plain",
    "render_telegram_html",
    "send_structured",
    "split_telegram_html",
    "to_plain",
    "to_telegram_chunks",
    "to_telegram_html",
    "utf16_units",
]
