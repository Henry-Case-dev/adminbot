"""ASAP 8 F1 (§1.2/§1.4 architecture) — granular detection + deterministic
repair of §99 L2-документов.

**Чистый модуль**: без LLM, без I/O, без durable-записей. Владелец валидации
— ``summary_l2_writer._validate``; этот модуль вызывается из публичного
``validate_l2_document`` ТОЛЬКО когда первый проход канонизации отверг
документ с umbrella-причиной ``invalid_paragraph``:

    granular detect -> deterministic repair -> revalidate (один проход)

Классы дефектов (P0-S1 ТЗ §2; аддитивно к ``REASON_*``, §28.1 — не
«переименование»: umbrella ``invalid_paragraph`` остаётся группой
``reason_group`` для совместимости аналитики):

============================  ==================  =========================
code                          deterministic       correctionable
                              repair
============================  ==================  =========================
``paragraph_bad_type``        нет                 да
(элемент ``text`` — не str)
``paragraph_empty``           удалить только      да (если всё опустело →
                              пустой элемент      ``document_no_paragraphs``)
``paragraph_too_long``        split по sentence   да (одиночное предложение
(> ``PARAGRAPH_MAX``)         boundary            > лимита не режется)
``paragraph_empty_after_``    удалить non-content да (если всё опустело)
``cleanup``                   элемент
``document_no_paragraphs``    нет                 да
============================  ==================  =========================

НЕ ремонтируется (fail-closed, §2.3 ТЗ «Не repair автоматически»):
invented evidence (``invalid_evidence`` — ссылки вне id-space пакета никогда
не «домываются»), wrong-person attribution (``quote_attribution``),
structurally broken JSON. S3: факт из вымышленной ссылки не создаётся.

R17: наружу только коды/индексы/длины (``Defect{code, index, chars}``,
``actions``) — текст абзацев не возвращается и не логируется.
"""
from __future__ import annotations

import dataclasses
import re

# ── Гранулярные коды (P0-S1) ────────────────────────────────────────────────

PARAGRAPH_BAD_TYPE = "paragraph_bad_type"
PARAGRAPH_EMPTY = "paragraph_empty"
PARAGRAPH_TOO_LONG = "paragraph_too_long"
PARAGRAPH_EMPTY_AFTER_CLEANUP = "paragraph_empty_after_cleanup"
DOCUMENT_NO_PARAGRAPHS = "document_no_paragraphs"

# ── Группы (umbrella, обратная совместимость аналитики) ─────────────────────

GROUP_INVALID_PARAGRAPH = "invalid_paragraph"
GROUP_INVALID_EVIDENCE = "invalid_evidence"
GROUP_QUOTE_ATTRIBUTION = "quote_attribution"
GROUP_STRUCTURAL = "structural"
GROUP_OK = "ok"

#: reason → reason_group (аддитивная модель §1.2; неизвестное → structural).
REASON_GROUPS: dict[str, str] = {
    "ok": GROUP_OK,
    # invalid_paragraph: umbrella + гранулярные абзацные коды.
    "invalid_paragraph": GROUP_INVALID_PARAGRAPH,
    PARAGRAPH_BAD_TYPE: GROUP_INVALID_PARAGRAPH,
    PARAGRAPH_EMPTY: GROUP_INVALID_PARAGRAPH,
    PARAGRAPH_TOO_LONG: GROUP_INVALID_PARAGRAPH,
    PARAGRAPH_EMPTY_AFTER_CLEANUP: GROUP_INVALID_PARAGRAPH,
    DOCUMENT_NO_PARAGRAPHS: GROUP_INVALID_PARAGRAPH,
    # fail-closed соседи (не ремонтируются детерминированно).
    "invalid_evidence": GROUP_INVALID_EVIDENCE,
    "quote_attribution": GROUP_QUOTE_ATTRIBUTION,
    # структурные (§99-схема/транспорт/внутреннее).
    "bad_type": GROUP_STRUCTURAL,
    "unknown_field": GROUP_STRUCTURAL,
    "bad_schema_version": GROUP_STRUCTURAL,
    "invalid_title": GROUP_STRUCTURAL,
    "invalid_emphasis": GROUP_STRUCTURAL,
    "too_many_paragraphs": GROUP_STRUCTURAL,
    "too_long": GROUP_STRUCTURAL,
    "invalid_json": GROUP_STRUCTURAL,
    "empty_response": GROUP_STRUCTURAL,
    "internal_error": GROUP_STRUCTURAL,
    "no_package": GROUP_STRUCTURAL,
    "package_not_deliverable": GROUP_STRUCTURAL,
    "not_built": GROUP_STRUCTURAL,
    "llm_error": GROUP_STRUCTURAL,
    "llm_timeout": GROUP_STRUCTURAL,
}

#: РОВНО ОДИН LLM-correction допустим для этих финальных причин (§2.4 ТЗ;
#: таблица §1.2 architecture). Repairable-дефекты до correction обычно не
#: доживают (детерминированный repair дешевле) — коды здесь на случай
#: post-repair остатка.
CORRECTIONABLE_REASONS: frozenset[str] = frozenset({
    PARAGRAPH_BAD_TYPE,
    PARAGRAPH_EMPTY,
    PARAGRAPH_TOO_LONG,
    PARAGRAPH_EMPTY_AFTER_CLEANUP,
    DOCUMENT_NO_PARAGRAPHS,
    "invalid_evidence",
    "quote_attribution",
    "invalid_json",
})

#: Коды с детерминированным ремонтом.
REPAIRABLE_CODES: frozenset[str] = frozenset({
    PARAGRAPH_EMPTY,
    PARAGRAPH_TOO_LONG,
    PARAGRAPH_EMPTY_AFTER_CLEANUP,
})

# Телеметрия repair_actions — bounded (R17: коды/индексы, не текст).
MAX_REPAIR_ACTIONS = 32


@dataclasses.dataclass(frozen=True)
class Defect:
    """Гранулярный дефект абзаца (R17-safe: без текста)."""

    code: str
    index: int          # индекс в paragraphs_raw; -1 — документ-уровень
    chars: int          # длина текста дефектного абзаца (0 — нет текста)


def reason_group(reason) -> str:
    """Umbrella-группа для granular/legacy кода (совместимость аналитики)."""
    return REASON_GROUPS.get(str(reason or ""), GROUP_STRUCTURAL)


def is_correctionable(reason) -> bool:
    """Разрешён ли РОВНО ОДИН LLM-correction для этой финальной причины."""
    return str(reason or "") in CORRECTIONABLE_REASONS


def granular_reason(defects: list[Defect]) -> str | None:
    """Точная причина по списку дефектов: документ-уровень приоритетнее
    абзацного (пустой среди пустых → ``document_no_paragraphs``)."""
    for defect in defects:
        if defect.code == DOCUMENT_NO_PARAGRAPHS:
            return defect.code
    for defect in defects:
        if defect.index >= 0:
            return defect.code
    return None


def detect_paragraph_defects(document, package=None) -> list[Defect]:
    """Гранулярная детекция paragraph-дефектов raw §99-документа.

    Порядок проверок абзаца зеркалит канонизацию ``_validate``:
    cleanup → strip → (пусто? | >900?) → strip сырых ID → пусто?
    Элементы-не-dict и битые типы ``emphasis`` — класс ``bad_type``
    (structural, вне repair-контракта) — здесь НЕ флагуются. Не бросает.
    """
    from services.summary_cleanup import cleanup_llm_text
    from services.summary_l2_writer import PARAGRAPH_MAX, _strip_raw_ids

    defects: list[Defect] = []
    if not isinstance(document, dict):
        return defects
    paragraphs = document.get("paragraphs")
    if not isinstance(paragraphs, list):
        return defects

    content_paragraphs = 0
    for index, element in enumerate(paragraphs):
        if not isinstance(element, dict):
            continue                     # bad_type — structural, не repair
        text_value = element.get("text")
        if not isinstance(text_value, str):
            # bad_type ПЕРЕЖИВАЕТ repair (элемент не выбрасывается) —
            # документ не «опустел».
            defects.append(Defect(PARAGRAPH_BAD_TYPE, index, 0))
            content_paragraphs += 1
            continue
        cleaned = cleanup_llm_text(text_value).strip()
        if not cleaned:
            defects.append(Defect(PARAGRAPH_EMPTY, index, 0))
            continue
        if len(cleaned) > PARAGRAPH_MAX:
            # too_long ПЕРЕЖИВАЕТ repair (split, либо как есть) — документ
            # не «опустел»; document_no_paragraphs здесь неуместен.
            defects.append(Defect(PARAGRAPH_TOO_LONG, index, len(cleaned)))
            content_paragraphs += 1
            continue
        stripped, _count = _strip_raw_ids(cleaned)
        if not stripped:
            defects.append(Defect(
                PARAGRAPH_EMPTY_AFTER_CLEANUP, index, len(cleaned)))
            continue
        content_paragraphs += 1

    if content_paragraphs == 0:
        # [] или все элементы отброшены — точка :1046-1047 (§1.1 аудита).
        defects.append(Defect(DOCUMENT_NO_PARAGRAPHS, -1, 0))
    return defects


# ── Deterministic repair ────────────────────────────────────────────────────

# Граница предложения: [.!?…]+ + пробел (детерминированно, без NLP).
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?…])\s+")


def _split_sentences(text: str) -> list[str]:
    parts = [chunk for chunk in _SENTENCE_BOUNDARY_RE.split(text)
             if chunk and chunk.strip()]
    return parts or ([text] if text.strip() else [])


def _pack_into_chunks(sentences: list[str], limit: int) -> list[str]:
    """Жадная упаковка предложений в chunks ≤ limit. ВЕСЬ текст сохраняется
    (§2.3 «не trim»): одиночное предложение > limit становится собственным
    chunk (> лимита — revalidate отвергнет,_correctionable)."""
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= limit:
            current = f"{current} {sentence}"
        else:
            chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def repair_document(document, package=None) -> tuple[dict | None, list[dict]]:
    """Deterministic repair §99-документа. ``(<doc'> | None, actions)``.

    Правила (§2.3 ТЗ):
      * ``paragraph_too_long`` — split по sentence boundary; весь текст
        сохраняется; ``evidence_message_ids`` наследуются каждой частью
        (shared evidence разрешён, §50.7) — refs «следуют за предложением»
        в смысле трассировки; emphasis spans пересчитает штатный
        канонизатор на revalidate (невалидные для части подстроки
        отбрасываются детерминированно, §99 v1.1 Q3);
      * ``paragraph_empty`` / ``paragraph_empty_after_cleanup`` — удалить
        ТОЛЬКО дефектный элемент, остальные не трогать;
      * одиночное предложение > лимита не режется (никогда не trim);
      * всё опустело → ``(None, actions)`` — причина
        ``document_no_paragraphs`` (correctionable), ремонта нет;
      * неремонтируемые дефекты (bad_type/пусто-структура) → без изменений.

    Раскладка выхода зафиксирована ``repair_projection`` (единый источник
    для anchor-проброса). Не бросает; возвращает НОВЫЙ dict (вход не
    мутируется).
    """
    if not isinstance(document, dict):
        return None, []
    paragraphs = document.get("paragraphs")
    if not isinstance(paragraphs, list):
        return None, []

    projection = repair_projection(document, package)
    if not projection:
        return None, []

    from services.summary_l2_writer import PARAGRAPH_MAX

    defects = detect_paragraph_defects(document, package)
    by_index: dict[int, Defect] = {}
    for defect in defects:
        if defect.index >= 0 and defect.index not in by_index:
            by_index[defect.index] = defect

    new_paragraphs: list = []
    actions: list[dict] = []
    for index, kind, parts in projection:
        element = paragraphs[index]
        if kind == "drop":
            # Удалить только пустой/non-content элемент (§2.3).
            actions.append({"action": "drop_paragraph",
                            "code": by_index[index].code, "index": index})
            continue
        if kind == "split":
            # PARAGRAPH_TOO_LONG → split по sentence boundary.
            text_value = element.get("text") \
                if isinstance(element, dict) else None
            chunks = _pack_into_chunks(
                _split_sentences(text_value), PARAGRAPH_MAX) \
                if isinstance(text_value, str) else []
            base = element if isinstance(element, dict) else {}
            for chunk in chunks:
                clone = dict(base)
                clone["text"] = chunk
                new_paragraphs.append(clone)
            actions.append({"action": "split_paragraph",
                            "code": by_index[index].code, "index": index,
                            "parts": len(chunks)})
            continue
        if kind == "skip":
            # Одиночное предложение > лимита: детерминированного ремонта
            # нет (trim запрещён) — элемент остаётся, correctionable.
            new_paragraphs.append(element)
            actions.append({"action": "split_skipped_single_sentence",
                            "code": by_index[index].code, "index": index})
            continue
        new_paragraphs.append(element)          # keep — байт-в-байт

    if len(actions) > MAX_REPAIR_ACTIONS:
        del actions[MAX_REPAIR_ACTIONS:]
        actions.append({"action": "actions_truncated"})
    if not new_paragraphs:
        # Всё опустело — ремонта нет, причина document_no_paragraphs.
        return None, actions

    repaired = dict(document)
    repaired["paragraphs"] = new_paragraphs
    return repaired, actions


def repair_projection(document, package=None) -> list[tuple[int, str, int]]:
    """Детерминированная проекция выхода ``repair_document`` по raw-индексам.

    ``[(raw_index, kind, parts)]`` в ПОРЯДКЕ ВЫХОДА ремонта:
      * ``"keep"``  — абзац проходит 1:1 (валидный / не-repairable);
      * ``"skip"``  — одиночное предложение > лимита, остаётся как есть
        (1 выход, action ``split_skipped_single_sentence``);
      * ``"drop"``  — абзац удалён (0 выходов);
      * ``"split"`` — абзац разбит на ``parts`` частей.

    Пустой список — ремонт НЕ применяется (identity: документ без
    изменений или ремонт невозможен). Используется
    ``validate_l2_document_anchors`` для проброса ``source_anchors`` с
    учётом split/drop: split-части наследуют якоря исходного абзаца
    (shared evidence, §50.7), drop исключает их — смещение якорей
    недопустимо. Не бросает.
    """
    if not isinstance(document, dict):
        return []
    paragraphs = document.get("paragraphs")
    if not isinstance(paragraphs, list):
        return []
    defects = detect_paragraph_defects(document, package)
    if not any(defect.code in REPAIRABLE_CODES for defect in defects):
        return []
    from services.summary_l2_writer import PARAGRAPH_MAX

    by_index: dict[int, Defect] = {}
    for defect in defects:
        if defect.index >= 0 and defect.index not in by_index:
            by_index[defect.index] = defect

    projection: list[tuple[int, str, int]] = []
    for index, element in enumerate(paragraphs):
        defect = by_index.get(index)
        if defect is None or defect.code not in REPAIRABLE_CODES:
            projection.append((index, "keep", 1))
            continue
        if defect.code in (PARAGRAPH_EMPTY, PARAGRAPH_EMPTY_AFTER_CLEANUP):
            projection.append((index, "drop", 0))
            continue
        # PARAGRAPH_TOO_LONG → split по sentence boundary.
        text_value = element.get("text") \
            if isinstance(element, dict) else None
        chunks = _pack_into_chunks(
            _split_sentences(text_value), PARAGRAPH_MAX) \
            if isinstance(text_value, str) else []
        if len(chunks) <= 1:
            projection.append((index, "skip", 1))
            continue
        projection.append((index, "split", len(chunks)))
    return projection


def post_repair_reason(defects: list[Defect], actions: list[dict]) -> str | None:
    """Точная причина, когда repair не дал документа (``doc' is None``)."""
    if actions and not any(
            action.get("action") == "split_skipped_single_sentence"
            for action in actions):
        # Удаляли пустые — и всё опустело.
        return DOCUMENT_NO_PARAGRAPHS
    return granular_reason(defects)


def applied_repairs(actions: list[dict]) -> int:
    """Число реально применённых ремонтов (drop/split) для телеметрии."""
    return sum(1 for action in (actions or [])
               if action.get("action") in ("drop_paragraph",
                                           "split_paragraph"))
