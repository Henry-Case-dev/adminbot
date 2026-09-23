"""S5 round1026 (ADR-1026-7 D2) + S6 round1026 (ADR-1026-11 D2/D7) — серверный
форматтер статьи §98/§99/§101/§102/§105.

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
    молчаливого обрезания; акценты абзацев рендерятся тем же каноном, что и
    ``format_plain_html`` (единый источник, B-R1026S6-2); ``sanitize``
    применяется ДО clean/escape (L-R1026S5-5: sanitize → clean → escape);
  * **rich_document_limits** — проверка вместимости rich-канала по **полному**
    тексту (``rich_paragraph_limit`` / ``rich_char_limit``): переполнение не
    срезается молча, вызывающий обязан уйти в plain-фолбэк (B-R1026S6-1).

S6-адаптеры (аддитивные, 0 LLM): ``extract_title_from_markdown`` — заголовок из
Markdown-строки digest Stage-1; ``document_from_plain_text`` — детерминированный
legacy-text → §99-документ для OFF-пути (заголовок по приоритету: явный →
первая короткая строка-абзац → первое предложение → нет заголовка; тело никогда
не обрезается); ``chunk_plain_text`` — абзацная нарезка plain-текста.

Экранирование — **кодом**: ``sanitize_outgoing`` (существующая обёртка egress)
→ затем ``html.escape(..., quote=True)`` (порядок обязателен — инвариант 3
``telegram_send``). Лимиты D2: ``title`` ≤200/одна строка, абзацев
≤ ``limits.max_summary_parts`` и ≤498, rich ≤32000, абзац ≤900;
``emphasis`` — дословная подстрока своего абзаца, иначе снимается. Ни один
путь не теряет текст молча: превышение rich-лимитов — сигнал
``rich_document_limits`` (даунгрейд в plain с полным текстом), не усечение.
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
# S6 (D2/§5.3): первая Markdown-заголовочная строка digest Stage-1.
_MD_TITLE_LINE_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*$")
# Граница предложения (для fallback-заголовка №3, spec §5.3).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
# Разбивка plain-текста на абзацы (пустая строка — граница).
_PARAGRAPH_SPLIT_RE = re.compile(r"\n{2,}")


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
    """Все валидные абзацы документа — без среза (B-R1026S6-1).

    Кап :data:`MAX_PARAGRAPHS_HARD` больше не применяется здесь: усечение
    документа в форматтере теряло бы текст молча. Вместимость rich-канала
    проверяется отдельно (:func:`rich_document_limits`), plain-путь доставляет
    все абзацы чанками (§105).
    """
    if not isinstance(document, dict):
        return []
    paragraphs = document.get("paragraphs")
    if not isinstance(paragraphs, list):
        return []
    out = []
    for paragraph in paragraphs:
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
    escape). Возвращает **полный** текст без усечения (B-R1026S6-1):
    вместимость rich-канала проверяет :func:`rich_document_limits` до
    отправки; молчаливого среза хвоста здесь нет.
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
    return "".join(parts)


def rich_document_limits(document, *, cover_id=None, sanitize=None) -> dict:
    """B-R1026S6-1: влезает ли rich-канал — по **полному** тексту, без среза.

    Чистая детерминированная проверка (0 LLM/сети) для решения о доставке:
    ``fits=False`` — rich-сообщение с полным текстом превысит лимиты Telegram
    (500 блоков → ``rich_paragraph_limit``; :data:`RICH_MAX_CHARS` символов →
    ``rich_char_limit``), и вызывающий обязан опубликовать plain-путём с
    полным текстом (§105/SC-20), а не срезать хвост.

    Возвращает ``{"html", "paragraphs", "html_len", "max_paragraphs",
    "max_chars", "fits", "reason"}``; ``reason == ""`` при ``fits=True``.
    """
    html = format_rich_html(document, cover_id=cover_id, sanitize=sanitize)
    paragraphs = len(_iter_paragraphs(document))
    if paragraphs > MAX_PARAGRAPHS_HARD:
        reason = "rich_paragraph_limit"
    elif len(html) > RICH_MAX_CHARS:
        reason = "rich_char_limit"
    else:
        reason = ""
    return {
        "html": html,
        "paragraphs": paragraphs,
        "html_len": len(html),
        "max_paragraphs": MAX_PARAGRAPHS_HARD,
        "max_chars": RICH_MAX_CHARS,
        "fits": not reason,
        "reason": reason,
    }


# ── Plain HTML (§105) ──────────────────────────────────────────────────────

def _plain_html_blocks(document, sanitize) -> list[str]:
    """Единый канон plain-блоков (§105): ``<b>title</b>`` + абзацы (≤1 ``<b>``).

    Один источник для предпросмотра (:func:`format_plain_html`) и фактической
    доставки (:func:`chunk_plain_blocks`) — B-R1026S6-2: абзацные акценты
    рендерятся одинаково, экранирование сохраняется (sanitize → clean →
    escape), пустые абзацы пропускаются.
    """
    title = _title_of(document)
    blocks: list[str] = []
    if title:
        blocks.append("<b>{}</b>".format(_escape(sanitize(title))))
    for paragraph in _iter_paragraphs(document):
        body = _render_plain_html_paragraph(
            paragraph.get("text", ""), _emphasis_of(paragraph,
                                                    _clean_text(paragraph.get("text", ""))),
            sanitize)
        if body:
            blocks.append(body)
    return blocks


def format_plain_html(document, *, sanitize=None) -> str:
    """§105: H1 → ``<b>title</b>``, абзацы отдельными блоками (``\\n\\n``).

    Без настоящего ``<h1>`` (обычный ``sendMessage``); акценты — совместимые
    ``<b>``. Экранирование — sanitize → escape. Весь текст без усечения.
    """
    sanitize = _sanitizer(sanitize)
    return "\n\n".join(_plain_html_blocks(document, sanitize))


def format_plain_text(document) -> str:
    """§105 финальный даунгрейд: низкоуровневый текст без разметки."""
    title = _title_of(document)
    blocks: list[str] = []
    if title:
        blocks.append(title)
    for paragraph in _iter_paragraphs(document):
        blocks.append(_clean_text(str(paragraph.get("text", ""))))
    return "\n\n".join(block for block in blocks if block)


# ── S6 (ADR-1026-11 D2/D7): адаптеры legacy-text → §99 (0 LLM) ─────────────

def extract_title_from_markdown(markdown: str) -> str:
    """Первая Markdown-заголовочная строка digest Stage-1 (§5.3, п.1).

    Чистая детерминированная функция: ``# Заголовок`` → ``Заголовок``
    (Markdown-разметка снимается ``_clean_text``, одна строка, ≤200).
    Нет заголовка → ``""``; выдуманный заголовок не создаётся.
    """
    source = str(markdown or "")
    if not source:
        return ""
    for match in _MD_TITLE_LINE_RE.finditer(source):
        candidate = _clean_text(match.group(1))
        if candidate:
            return re.sub(r"\s+", " ", candidate).strip()[:TITLE_MAX]
    return ""


def _extract_title_from_blocks(blocks: list[str]) -> tuple[str, list[str]]:
    """Заголовок из plain-текста по приоритету §5.3 (пп.2–4), 0 LLM.

    * первая строка — отдельный короткий абзац ≤200 и далее есть текст;
    * иначе первое предложение первого абзаца ≤200 с непустым остатком;
    * иначе заголовка нет (тело НЕ обрезается ради заголовка).

    Возвращает ``(title, body_blocks)``: изъятый в заголовок фрагмент уходит
    из тела (публикуется заголовком — потери текста нет).
    """
    if not blocks:
        return "", []
    first, rest = blocks[0], blocks[1:]
    if "\n" not in first and rest and len(first) <= TITLE_MAX:
        return first, rest
    match = _SENTENCE_SPLIT_RE.search(first)
    if match:
        candidate = first[:match.start()].strip()
        remainder = first[match.end():].strip()
        if candidate and remainder and len(candidate) <= TITLE_MAX:
            return candidate, [remainder] + rest
    return "", list(blocks)


def document_from_plain_text(text: str, *, title: str = "") -> dict:
    """Детерминированный legacy-text → §99-документ (OFF-путь, 0 LLM).

    Абзацы — по пустой строке; явный ``title`` (например, из digest Stage-1)
    приоритетен, иначе заголовок извлекается по §5.3 (пп.2–4). Markdown-
    разметка снимается на этапе форматирования (``_clean_text``); вход не
    мутируется; двойной прогон байт-идентичен.
    """
    source = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = [block.strip() for block in _PARAGRAPH_SPLIT_RE.split(source)]
    blocks = [block for block in blocks if block]
    clean_title = re.sub(r"\s+", " ", _clean_text(str(title or ""))).strip()
    body = list(blocks)
    if not clean_title:
        clean_title, body = _extract_title_from_blocks(blocks)
    clean_title = re.sub(r"\s+", " ", _clean_text(clean_title)).strip()
    return {
        "schema_version": 1,
        "title": clean_title[:TITLE_MAX],
        "paragraphs": [{"text": block, "emphasis": None} for block in body],
    }


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


def _pack_blocks(blocks: list[str], limit_value: int) -> list[str]:
    """Greedy-упаковка блоков в чанки ≤ limit по границам абзацев (§105)."""
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


def _limit_or_default(limit) -> int:
    try:
        limit_value = int(limit)
    except (TypeError, ValueError):
        limit_value = PLAIN_CHUNK_LIMIT
    return limit_value if limit_value > 0 else PLAIN_CHUNK_LIMIT


def chunk_plain_blocks(document, limit: int = PLAIN_CHUNK_LIMIT,
                       sanitize=None) -> list[str]:
    """Разбить документ на блоки ≤ ``limit`` **по границам абзацев** (§105).

    Ни один абзац не режется посередине (абзац ≤900 < 4096); текст не теряется.
    ``sanitize`` (L-R1026S5-5) применяется ДО ``_clean_text``/``_escape`` —
    реальный порядок sanitize → clean → escape. Абзацные ``<b>``-акценты
    рендерятся тем же каноном, что и :func:`format_plain_html` (единый
    источник, B-R1026S6-2): ≤1 ``<b>`` на абзац, экранирование сохраняется.
    """
    limit_value = _limit_or_default(limit)
    sanitize = _sanitizer(sanitize)
    return _pack_blocks(_plain_html_blocks(document, sanitize), limit_value)


def chunk_plain_text(text: str, limit: int = PLAIN_CHUNK_LIMIT) -> list[str]:
    """Разбить plain-текст ≤ ``limit`` **по границам абзацев** (§105).

    Используется финальным даунгрейдом (``format_plain_text``): разметки нет,
    поэтому экранирование/сущности не требуются; ни один абзац не теряется.
    """
    limit_value = _limit_or_default(limit)
    blocks = [block.strip()
              for block in _PARAGRAPH_SPLIT_RE.split(str(text or ""))]
    blocks = [block for block in blocks if block]
    if not blocks:
        return []
    return _pack_blocks(blocks, limit_value)
