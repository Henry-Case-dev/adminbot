"""S5 round1026 (ADR-1026-7 D2) + S6 round1026 (ADR-1026-11 D2/D7) — серверный
форматтер статьи §98/§99/§101/§102/§105.

ASAP-2.1 (ADR-1028-1 D3/D4): §99 v1.1 — секвенциальный рендер принятых
``emphasis_spans`` (≤1 `<b>` на абзац заменён walk-рендером списка; derived-
``emphasis`` — fallback при пустом списке) + **детерминированный Rich cut**:
при len(абзацев) > 1 всё после первого абзаца (и finale) уходит под ОДИН
закрытый ``<details><summary>Читать дальше</summary>`` (0–1 абзац — ката нет).
Cut — presentation layer: документ не меняется, plain-каналы отдают ПОЛНЫЙ
текст без ката; ``rich_document_limits`` считает лимиты по полному HTML
(обёртка ~50–60 симв. внутри headroom 32000).

**Чистый детерминированный** модуль (stdlib; без БД/сети/LLM/часов): превращает
структурированный §99-документ в Telegram-канальные представления:

  * **rich HTML** (§101/§102, основной путь): ``<img src="tg://photo?id=…">``
    (если задана обложка), затем **настоящий `<h1>`**, затем ``<p>`` с `<b>`-
    акцентами по принятым спанам + deterministic cut; теги ``img/h1/p/b``
    + ``details/summary`` (только cut-обёртка); MarkdownV2 не смешивается;
  * **plain HTML** (§105, fallback без обложки): ``<b>title</b>`` + абзацы/
    совместимые ``<b>``-акценты через ``sendMessage parse_mode="HTML"`` —
    БЕЗ ката (полный текст, §1:2837);
  * **plain text** (§105, финальный даунгрейд) — без разметки, полный текст;
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
``telegram_send``). Лимиты D2 (технические, §99/§101): ``title`` ≤200/одна
строка, абзацев ≤498 (единственный кап статьи), rich ≤32000, абзац ≤900;
спаны — дословные подстроки своего абзаца, иначе игнор. Ни один путь не теряет
текст молча: превышение rich-лимитов — сигнал ``rich_document_limits``
(даунгрейд в plain с полным текстом), не усечение.
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

# Разрешённые теги rich-пути (§102 + ADR-1028-1 D4): img/h1/p/b + cut.
_RICH_TAG_RE = re.compile(r"</?(?:img|h1|p|b|details|summary)\b")
_MD_HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
_MD_BULLET_RE = re.compile(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+")
_MD_EMPHASIS_RE = re.compile(r"(\*\*|__|`)")
# S6 (D2/§5.3): первая Markdown-заголовочная строка digest Stage-1.
_MD_TITLE_LINE_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*$")
# Граница предложения (для fallback-заголовка №3, spec §5.3).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
# Разбивка plain-текста на абзацы (пустая строка — граница).
_PARAGRAPH_SPLIT_RE = re.compile(r"\n{2,}")

# Детерминированный cut (§1/ADR-1028-1 D4): текст summary константен.
CUT_SUMMARY_TEXT = "Читать дальше"


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


def _emphasis_spans_of(paragraph, clean_text: str) -> list[str]:
    """Принятые спаны абзаца — дословные подстроки СВОЕГО текста (D3).

    Рендер идёт по ``emphasis_spans``; при пустом/отсутствующем списке —
    по legacy ``emphasis`` (совместимость документов прежнего канона и
    plain-адаптера). Invalid/чужой-абзац спан игнорируется (defense:
    валидатор уже отфильтровал, здесь — последняя линия).
    """
    raw_spans = paragraph.get("emphasis_spans")
    candidates: list[str] = []
    if isinstance(raw_spans, list) and raw_spans:
        for span in raw_spans:
            if isinstance(span, dict):
                value = span.get("text")
            else:
                value = span
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
    else:
        legacy = paragraph.get("emphasis")
        if isinstance(legacy, str) and legacy.strip():
            candidates.append(legacy.strip())
    out: list[str] = []
    for candidate in candidates:
        if candidate in clean_text and candidate not in out:
            out.append(candidate)
    return out


def _resolve_span_positions(spans: list[str], clean_text: str) -> list:
    """Детерминированные позиции (первое вхождение; сортировка
    ``(start ASC, length DESC, порядок ASC)``; жадный приём без пересечений)."""
    positioned = [(clean_text.find(s), -len(s), order, s)
                  for order, s in enumerate(spans)
                  if clean_text.find(s) >= 0]
    positioned.sort(key=lambda item: (item[0], item[1], item[2]))
    accepted: list = []
    last_end = -1
    for start, neg_len, _order, span in positioned:
        if start < last_end:
            continue
        accepted.append((start, span))
        last_end = start + len(span)
    return accepted


def _render_with_spans(clean_text: str, spans: list[str], escape) -> str:
    """Секвенциальный walk-рендер: текст между спанами escape, каждый спан —
    в ``<b>…</b>`` (тоже escape). Один и тот же код для rich и plain-HTML."""
    accepted = _resolve_span_positions(spans, clean_text)
    if not accepted:
        return escape(clean_text)
    parts: list[str] = []
    cursor = 0
    for start, span in accepted:
        parts.append(escape(clean_text[cursor:start]))
        parts.append("<b>" + escape(span) + "</b>")
        cursor = start + len(span)
    parts.append(escape(clean_text[cursor:]))
    return "".join(parts)


def _render_plain_html_paragraph(text: str, spans, sanitize) -> str:
    """Один ``<p>``-блок абзаца с ``<b>``-акцентами; sanitize ДО escape."""
    clean = _clean_text(sanitize(text))
    return _render_with_spans(clean, spans, _escape)


def _finale_of(document) -> str:
    """Валидированный ``finale`` (§99 v1.1/Q4): одна строка ≤200, иначе ''."""
    if not isinstance(document, dict):
        return ""
    finale = document.get("finale")
    if not isinstance(finale, str):
        return ""
    cleaned = re.sub(r"\s+", " ", finale).strip()
    if not cleaned or len(cleaned) > 200:
        return ""
    return cleaned


# ── Rich HTML (§101/§102 + ADR-1028-1 D4) ──────────────────────────────────

def format_rich_html(document, *, cover_id=None, sanitize=None) -> str:
    """§99-документ → Rich HTML с детерминированным cut.

    Порядок обязателен (§101 + ADR-1028-1 D4): обложка первой, заголовок —
    **настоящий** ``<h1>``, ``<p>`` абзац 1; при **len(абзацев) > 1** — ОДИН
    закрытый ``<details><summary>Читать дальше</summary>`` с абзацами 2..N и
    finale-блоком внутри (атрибут ``open`` НЕ ставится). 0–1 абзац → ката нет,
    finale — видимый концевой блок. Cut — presentation layer: документ не
    меняется, plain-каналы отдают полный текст. Возвращает **полный** текст
    без усечения; вместимость rich-канала проверяет
    :func:`rich_document_limits` до отправки.
    """
    sanitize = _sanitizer(sanitize)
    title = _title_of(document)
    paragraphs = _iter_paragraphs(document)
    finale = _finale_of(document)
    parts: list[str] = []
    if cover_id:
        parts.append('<img src="tg://photo?id={}">'.format(_escape(str(cover_id))))
    if title:
        parts.append("<h1>{}</h1>".format(_escape(sanitize(title))))

    def _paragraph_html(paragraph) -> str:
        body = _render_plain_html_paragraph(
            paragraph.get("text", ""),
            _emphasis_spans_of(paragraph, _clean_text(paragraph.get("text", ""))),
            sanitize)
        return "<p>{}</p>".format(body)

    def _finale_html() -> str:
        if not finale:
            return ""
        return "<p>{}</p>".format(_escape(sanitize(finale)))

    cut = len(paragraphs) > 1
    if paragraphs:
        parts.append(_paragraph_html(paragraphs[0]))
    if cut:
        parts.append("<details><summary>{}</summary>".format(
            _escape(CUT_SUMMARY_TEXT)))
        for paragraph in paragraphs[1:]:
            parts.append(_paragraph_html(paragraph))
        parts.append(_finale_html())
        parts.append("</details>")
    else:
        parts.append(_finale_html())
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
    """Единый канон plain-блоков (§105): ``<b>title</b>`` + абзацы + finale.

    Один источник для предпросмотра (:func:`format_plain_html`) и фактической
    доставки (:func:`chunk_plain_blocks`) — B-R1026S6-2: абзацные акценты
    рендерятся одинаково (тот же walk-рендер спанов, ADR-1028-1 D3),
    экранирование сохраняется (sanitize → clean → escape), пустые абзацы
    пропускаются. ``finale`` — последним блоком (полный текст, §20;
    ADR-1028-1 Q4). Ката здесь НЕТ: plain-канал — полный текст.
    """
    title = _title_of(document)
    blocks: list[str] = []
    if title:
        blocks.append("<b>{}</b>".format(_escape(sanitize(title))))
    for paragraph in _iter_paragraphs(document):
        body = _render_plain_html_paragraph(
            paragraph.get("text", ""),
            _emphasis_spans_of(paragraph, _clean_text(paragraph.get("text", ""))),
            sanitize)
        if body:
            blocks.append(body)
    finale = _finale_of(document)
    if finale:
        blocks.append(_escape(sanitize(finale)))
    return blocks


def format_plain_html(document, *, sanitize=None) -> str:
    """§105: H1 → ``<b>title</b>``, абзацы отдельными блоками (``\\n\\n``).

    Без настоящего ``<h1>`` (обычный ``sendMessage``); акценты — совместимые
    ``<b>``. Экранирование — sanitize → escape. Весь текст без усечения.
    """
    sanitize = _sanitizer(sanitize)
    return "\n\n".join(_plain_html_blocks(document, sanitize))


def format_plain_text(document) -> str:
    """§105 финальный даунгрейд: низкоуровневый текст без разметки, ПОЛНЫЙ
    текст (включая finale последним блоком — ADR-1028-1 Q4/§20)."""
    title = _title_of(document)
    blocks: list[str] = []
    if title:
        blocks.append(title)
    for paragraph in _iter_paragraphs(document):
        blocks.append(_clean_text(str(paragraph.get("text", ""))))
    finale = _finale_of(document)
    if finale:
        blocks.append(finale)
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
