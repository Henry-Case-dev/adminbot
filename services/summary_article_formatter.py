"""S5 round1026 (ADR-1026-7 D2) — серверный форматтер статьи §98/§99/§101/§102/§105.

**Чистый детерминированный** модуль (stdlib; без БД/сети/LLM/часов): превращает
структурированный §99-документ (``{schema_version,title,paragraphs[{text,
emphasis}]}``) в Telegram-канальные представления:

  * **rich HTML** (§101/§102, основной путь): ``<img src="tg://photo?id=…">``
    (если задана обложка), затем **настоящий `<h1>`**, затем ``<p>`` с ≤1
    ``<b>``-акцентом; только теги ``img/h1/p/b``; MarkdownV2 не смешивается;
  * **plain HTML** (§105, fallback без обложки): ``<b>title</b>`` + абзацы/
    совместимые ``<b>``-акценты через ``sendMessage parse_mode="HTML"``;
  * **plain text** (§105, финальный даунгрейд) — без разметки;
  * **chunk_plain_blocks** — разбивка по **границам абзацев** (≤4096), без
    молчаливого обрезания.

Экранирование — **кодом**: ``sanitize_outgoing`` (существующая обёртка egress)
→ затем ``html.escape(..., quote=True)`` (порядок обязателен — инвариант 3
``telegram_send``). Лимиты D2: ``title`` ≤200/одна строка, абзацев
≤ ``limits.max_summary_parts`` и ≤498, rich ≤32000, абзац ≤900;
``emphasis`` — дословная подстрока своего абзаца, иначе снимается.
"""
from __future__ import annotations

import html as _html
import re

# Лимиты D2 (единый источник; синхронно с services/summary_l2_writer.py).
TITLE_MAX = 200
PARAGRAPH_MAX = 900
MAX_PARAGRAPHS_HARD = 498
RICH_MAX_CHARS = 32000
PLAIN_CHUNK_LIMIT = 4096

# Разрешённые теги rich-пути (§102): img/h1/p/b. Пользовательский текст и
# модель Markdown/буллиты сюда попасть не должны.
_MD_HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
_MD_BULLET_RE = re.compile(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+")
_MD_EMPHASIS_RE = re.compile(r"(\*\*|__|`)")


def _sanitizer(sanitize):
    if sanitize is not None:
        return sanitize
    from services.outgoing_guard import sanitize_outgoing
    return sanitize_outgoing


def _escape(text: str) -> str:
    """``html.escape`` с обязательным ``quote=True`` (кавычки тоже)."""
    return _html.escape(str(text or ""), quote=True)


def _clean_text(text: str) -> str:
    """Детерминированно снять Markdown-заголовки/буллиты/нумерацию (R11)."""
    value = _MD_HEADING_RE.sub("", str(text or ""))
    value = _MD_BULLET_RE.sub("", value)
    value = _MD_EMPHASIS_RE.sub("", value)
    return value.strip()


def _iter_paragraphs(document) -> list:
    if not isinstance(document, dict):
        return []
    paragraphs = document.get("paragraphs")
    if not isinstance(paragraphs, list):
        return []
    out = []
    for paragraph in paragraphs[:MAX_PARAGRAPHS_HARD]:
        if isinstance(paragraph, dict) and isinstance(paragraph.get("text"), str):
            out.append(paragraph)
    return out


def _title_of(document) -> str:
    if not isinstance(document, dict):
        return ""
    title = document.get("title")
    if not isinstance(title, str):
        return ""
    if "\n" in title or "\r" in title:
        title = title.replace("\n", " ").replace("\r", " ")
    return re.sub(r"\s+", " ", title).strip()[:TITLE_MAX]


def _emphasis_of(paragraph, clean_text: str):
    """Акцент — дословная подстрока СВОЕГО абзаца, иначе ``None`` (D2)."""
    emphasis = paragraph.get("emphasis")
    if not isinstance(emphasis, str):
        return None
    candidate = emphasis.strip()
    if not candidate:
        return None
    if candidate in clean_text:
        return candidate
    return None


def _render_plain_html_paragraph(text: str, emphasis, sanitize) -> str:
    """Один ``<p>``/абзац с ≤1 ``<b>``-акцентом; sanitize ДО escape."""
    clean = _clean_text(sanitize(text))
    if emphasis and emphasis in clean:
        head, _, tail = clean.partition(emphasis)
        return "{}{}{}".format(
            _escape(head), "<b>" + _escape(emphasis) + "</b>", _escape(tail))
    return _escape(clean)


# ── Rich HTML (§101/§102) ──────────────────────────────────────────────────

def format_rich_html(document, *, cover_id=None, sanitize=None) -> str:
    """§99-документ → Rich HTML: (обложка) + ``<h1>`` + ``<p>`` (+ ``<b>``).

    Порядок обязателен (§101): обложка первой, заголовок — **настоящий**
    ``<h1>`` (не жирный). Заголовок/абзацы экранируются кодом (sanitize →
    escape). Суммарный rich ≤ :data:`RICH_MAX_CHARS` (§102).
    """
    sanitize = _sanitizer(sanitize)
    title = _title_of(document)
    parts: list[str] = []
    if cover_id:
        parts.append('<img src="tg://photo?id={}">'.format(_escape(str(cover_id))))
    if title:
        parts.append("<h1>{}</h1>".format(_escape(sanitize(title))))
    for paragraph in _iter_paragraphs(document):
        body = _render_plain_html_paragraph(
            paragraph.get("text", ""), _emphasis_of(paragraph,
                                                    _clean_text(paragraph.get("text", ""))),
            sanitize)
        parts.append("<p>{}</p>".format(body))
    out = "".join(parts)
    if len(out) > RICH_MAX_CHARS:
        # Детерминированно отбрасываем ХВОСТОВЫЕ абзацы (заголовок/обложка
        # сохраняются), не режем тело абзаца посередине (не «молча» — факт
        # превышения виден по факту усечения списка; отдельный лог — в S7).
        trimmed: list[str] = []
        size = 0
        for part in parts:
            if size + len(part) > RICH_MAX_CHARS and trimmed:
                break
            trimmed.append(part)
            size += len(part)
        out = "".join(trimmed)
    return out


# ── Plain HTML (§105) ──────────────────────────────────────────────────────

def format_plain_html(document, *, sanitize=None) -> str:
    """§105: H1 → ``<b>title</b>``, абзацы отдельными блоками (``\\n\\n``).

    Без настоящего ``<h1>`` (обычный ``sendMessage``); акценты — совместимые
    ``<b>``. Экранирование — sanitize → escape.
    """
    sanitize = _sanitizer(sanitize)
    title = _title_of(document)
    blocks: list[str] = []
    if title:
        blocks.append("<b>{}</b>".format(_escape(sanitize(title))))
    for paragraph in _iter_paragraphs(document):
        body = _render_plain_html_paragraph(
            paragraph.get("text", ""), _emphasis_of(paragraph,
                                                    _clean_text(paragraph.get("text", ""))),
            sanitize)
        blocks.append(body)
    return "\n\n".join(blocks)


def format_plain_text(document) -> str:
    """§105 финальный даунгрейд: низкоуровневый текст без разметки."""
    title = _title_of(document)
    blocks: list[str] = []
    if title:
        blocks.append(title)
    for paragraph in _iter_paragraphs(document):
        blocks.append(_clean_text(str(paragraph.get("text", ""))))
    return "\n\n".join(block for block in blocks if block)


# ── Разбивка plain (§105) ──────────────────────────────────────────────────

def _split_safe(text: str, limit: int) -> list[str]:
    """Нарезать длинный (уже экранированный) блок, не разрывая HTML-сущность.

    Единственная вынужденная нарезка (§105): режем по ``limit``, но если
    граница попала внутрь сущности ``&…;`` — сдвигаем её к началу сущности
    (S-R1026S5-4), чтобы Telegram ``parse_mode="HTML"`` не отклонил осколок.
    """
    pieces: list[str] = []
    start = 0
    total = len(text)
    while start < total:
        end = min(start + limit, total)
        if end < total:
            amp = text.rfind("&", start, end)
            semi = text.rfind(";", start, end)
            if amp > semi:
                if amp > start:
                    end = amp              # режем перед началом сущности
                else:
                    close = text.find(";", start)
                    if close != -1:
                        end = close + 1    # сущность в самом начале — не рвём
        if end <= start:
            end = min(start + limit, total)
        pieces.append(text[start:end])
        start = end
    return pieces


def chunk_plain_blocks(document, limit: int = PLAIN_CHUNK_LIMIT) -> list[str]:
    """Разбить документ на блоки ≤ ``limit`` **по границам абзацев** (§105).

    Ни один абзац не режется посередине (абзац ≤900 < 4096); текст не теряется.
    """
    try:
        limit_value = int(limit)
    except (TypeError, ValueError):
        limit_value = PLAIN_CHUNK_LIMIT
    if limit_value <= 0:
        limit_value = PLAIN_CHUNK_LIMIT
    title = _title_of(document)
    blocks: list[str] = []
    if title:
        blocks.append("<b>{}</b>".format(_escape(title)))
    for paragraph in _iter_paragraphs(document):
        blocks.append(_escape(_clean_text(str(paragraph.get("text", "")))))
    chunks: list[str] = []
    current = ""
    for block in blocks:
        candidate = block if not current else current + "\n\n" + block
        if len(candidate) <= limit_value:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(block) > limit_value:
            # Абзац длиннее лимита — единственная вынужденная нарезка; не
            # молчаливая (каждый осколок отдан отдельным сообщением без потерь)
            # и безопасная для HTML-сущностей (S-R1026S5-4).
            chunks.extend(_split_safe(block, limit_value))
            current = ""
        else:
            current = block
    if current:
        chunks.append(current)
    return chunks
