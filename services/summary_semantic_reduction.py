"""ASAP-3.2 (round 1029, ADR-1028-5 D8/D9) — hierarchical semantic reduction.

Иерархическая семантическая редукция пакета фактов (§39) ВМЕСТО
позиционного усечения (§37/§38): L1 (exhaustive/chunk_all) отдаёт FULL
source set; при несоответствии бюджету L2 редукция СЖИМАЕТ дубликаты, а НЕ
выбрасывает уникальность:

```text
all L1 outputs
→ stable-ID merge (факты по нормализованному тексту, evidence union)
→ topic dedupe (темы с одинаковым нормализованным названием → одна)
→ cross-thread fragment dedupe (один message_id — один fragment)
→ merge reduced subpackages → final L2 package
```

§40 — МОЖНО сжимать: повторяющиеся fragments, duplicate evidence, одну тему
в нескольких chunks, verbose description. НЕЛЬЗЯ silently выбрасывать:
уникальный факт / участника / событие / тему → ``unique_dropped = 0``
(§41) — норма; позиционные каскады остаются ТОЛЬКО fail-soft последней
линии (в ``summary_fact_package``, с видимым degraded-событием).

Чистый модуль (0 LLM, stdlib + проектные утилиты): вход не мутируется,
детерминированно, двойной прогон байт-идентичен. Δ SQLite DDL = 0
(runtime-метрики).
"""
from __future__ import annotations

import dataclasses
import re

# Метрики §41: сколько проходов редукции максимум (детерминированный пайплайн
# стабилизируется за 1–2 прохода; потолок — защита от патологий).
MAX_REDUCTION_PASSES = 3

_WS_RE = re.compile(r"\s+")


@dataclasses.dataclass
class ReductionStats:
    """Coverage-метрики §41 (R17-safe: только числа; ``unique_dropped`` в
    редукции ВСЕГДА 0 — уникальный контент не выбрасывается)."""

    unique_before: int = 0
    unique_after: int = 0
    merged_duplicates: int = 0
    unique_dropped: int = 0
    passes: int = 0
    topics_merged: int = 0
    facts_merged: int = 0
    fragments_deduped: int = 0

    def as_dict(self) -> dict:
        return {
            "unique_before": self.unique_before,
            "unique_after": self.unique_after,
            "merged_duplicates": self.merged_duplicates,
            "unique_dropped": self.unique_dropped,
            "passes": self.passes,
            "topics_merged": self.topics_merged,
            "facts_merged": self.facts_merged,
            "fragments_deduped": self.fragments_deduped,
        }


def _norm_key(text) -> str:
    """Stable-ID нормализация (casefold + схлопывание пробелов)."""
    return _WS_RE.sub(" ", str(text or "").strip()).casefold()


def _semantic_identity(threads) -> tuple[set, set]:
    """Уникальные семантические элементы (§41): (fact-keys, fragment-keys).
    Fragment-ключ = (message_id, part) — части сегментации различимы."""
    facts: set = set()
    fragments: set = set()
    for thread in threads:
        for fact in thread.get("facts") or []:
            facts.add(_norm_key(fact.get("text")))
        for fragment in thread.get("fragments") or []:
            fragments.add((fragment.get("message_id"),
                           fragment.get("part")))
    return facts, fragments


def _occurrences(threads) -> int:
    """Число вхождений единиц контента (facts+fragments) по всем темам —
    разница до/после = сколько ПОВТОРОВ схлопнуто (merged, §41)."""
    total = 0
    for thread in threads:
        total += len(thread.get("facts") or [])
        total += len(thread.get("fragments") or [])
    return total


def _merge_duplicate_topics(threads, stats: ReductionStats) -> list:
    """Topic dedupe (§39/§40): темы с одинаковым нормализованным названием
    (одна тема, повторённая в нескольких chunks) → одна; union chronology
    (по message_id), факты — через fact-dedupe, fragments — через
    fragment-dedupe, evidence union. Ничего не теряется."""
    merged: list = []
    index_by_name: dict = {}
    for thread in threads:
        name = str(thread.get("name") or "")
        key = _norm_key(name)
        target = index_by_name.get(key)
        if target is None or not key:
            copy = dict(thread)
            merged.append(copy)
            if key:
                index_by_name[key] = copy
            continue
        stats.topics_merged += 1
        # union chronology по message_id (порядок восстановит сборщик ASC)
        seen_mids = {entry.get("message_id")
                     for entry in (target.get("chronology") or [])}
        for entry in thread.get("chronology") or []:
            if entry.get("message_id") not in seen_mids:
                target.setdefault("chronology", []).append(entry)
                seen_mids.add(entry.get("message_id"))
        # факты — объединяются (дальнейший fact-dedupe схлопнет повторы)
        target["facts"] = list(target.get("facts") or []) + list(
            thread.get("facts") or [])
        # fragments — объединяются (fragment-dedupe уберёт повторы)
        target["fragments"] = list(target.get("fragments") or []) + list(
            thread.get("fragments") or [])
        # evidence_ids — union (ASC у сборщика)
        for eid in thread.get("evidence_ids") or []:
            if eid not in (target.get("evidence_ids") or []):
                target.setdefault("evidence_ids", []).append(eid)
    return merged


def _dedupe_thread_facts(thread, stats: ReductionStats) -> None:
    """Duplicate evidence (§40): факты с одинаковым нормализованным текстом
    схлопываются, evidence_message_ids ОБЪЕДИНЯЮТСЯ (ни один ID не теряется)."""
    seen: dict = {}
    result: list = []
    for fact in thread.get("facts") or []:
        key = _norm_key(fact.get("text"))
        target = seen.get(key)
        if target is None:
            copy = {"text": fact.get("text"),
                    "evidence_message_ids": list(
                        fact.get("evidence_message_ids") or [])}
            result.append(copy)
            seen[key] = copy
            continue
        stats.facts_merged += 1
        for eid in fact.get("evidence_message_ids") or []:
            if eid not in target["evidence_message_ids"]:
                target["evidence_message_ids"].append(eid)
    thread["facts"] = result


def _dedupe_cross_thread_fragments(threads, stats: ReductionStats) -> None:
    """Повторяющиеся fragments (§40): один (message_id, part) остаётся
    fragment'ом ТОЛЬКО в первой теме (ASC-порядок входа); в остальных темах
    fragment убирается — chronology/topic_ids сохраняют знание о
    many-to-many принадлежности (контекст не теряется, дубликат текста —
    да). Части lossless-сегментации (§42: один message_id, разные ``part``)
    НЕ считаются дубликатами — все части сохраняются в своей теме."""
    seen: set = set()
    for thread in threads:
        kept: list = []
        for fragment in thread.get("fragments") or []:
            key = (fragment.get("message_id"), fragment.get("part"))
            if key in seen:
                stats.fragments_deduped += 1
                continue
            seen.add(key)
            kept.append(fragment)
        thread["fragments"] = kept


def reduce_threads(threads) -> tuple[list, ReductionStats]:
    """Полный проход hierarchical semantic reduction (§39) над собранными
    темами пакета. Вход НЕ мутируется. Возвращает ``(threads, stats)``;
    ``stats.unique_dropped`` в редукции всегда 0 (§41): каждый УНИКАЛЬНЫЙ
    семантический ключ сохраняется; ``merged_duplicates`` — сколько
    ПОВТОРОВ (неуникальных вхождений) схлопнуто."""
    stats = ReductionStats()
    if not threads:
        return [], stats
    facts_before, fragments_before = _semantic_identity(threads)
    stats.unique_before = len(facts_before) + len(fragments_before)
    occurrences_before = _occurrences(threads)

    working = [dict(t) for t in threads]
    for _ in range(MAX_REDUCTION_PASSES):
        stats.passes += 1
        before_facts, before_frags = _semantic_identity(working)
        working = _merge_duplicate_topics(working, stats)
        for thread in working:
            _dedupe_thread_facts(thread, stats)
        _dedupe_cross_thread_fragments(working, stats)
        after_facts, after_frags = _semantic_identity(working)
        if (len(before_facts) == len(after_facts)
                and len(before_frags) == len(after_frags)):
            break                    # стабилизировалось
    facts_after, fragments_after = _semantic_identity(working)
    stats.unique_after = len(facts_after) + len(fragments_after)
    # Контроль корректности: ни один уникальный ключ не потерян (§40).
    lost = (facts_before - facts_after) | (fragments_before - fragments_after)
    stats.unique_dropped = len(lost)
    # merged = схлопнутые ПОВТОРЫ (вхождения) + слитые темы-дубликаты
    # («одна тема, повторённая в нескольких chunks», §40) — без потери.
    stats.merged_duplicates = (max(0, occurrences_before
                                   - _occurrences(working))
                               + stats.topics_merged)
    return working, stats
