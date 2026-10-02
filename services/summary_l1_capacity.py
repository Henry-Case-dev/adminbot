"""ASAP-4 волна C (epic `asap-4-embedding-graphrag-cover-runtime`) — L1
capacity guard (spec §3 C.1, ADR-1028-7 D7.1; T-4422; ТЗ §50.36/§51/§52).

Прод-болезнь (Q17): окно 688 сообщений влезло в бюджет ОДНОГО L1-запроса
(tokens_in=46118, chunks=1) → модель закономерно нашла 31+ фактов в широком
топике → ``too_many_facts`` → whole-run ``invalid`` → fallback-пакет
(fragments=30) → L2 упал на цитате → Legacy обрезал XML 50k до 307/688 молча.

Контракт (§50.36): ``MAX_FACTS_PER_THREAD=30`` / ``MAX_FACTS_TOTAL=1000`` —
потолки безопасности СТРУКТУРЫ, не «гильотина» качества. Нормальный плотный
чат не становится invalid из-за произвольного капа. До валидации:

  * **planning estimate до model call** (§52): source size, message count,
    reply density, expected topics/facts, output reserve → при высокой
    плотности ЗАРАНЕЕ больше L1-чанков (semantic sharding), а не только по
    входным токенам;
  * **переполнение после модели** (§51): deterministic repair БЕЗ нового
    LLM-вызова — reduce duplicates (дедуп фактов, union evidence) → split
    semantic subthread (тред >30 фактов → подсмыслы ≤30) → allocate output
    budget (детерминированное вытеснение по минимуму evidence при тотальном
    переполнении, видимое счётчиком);
  * **после merge** — тот же repair приводит объединённый payload к капам
    (reduction до бюджета L2 делает ``summary_fact_package``/
    ``summary_semantic_reduction`` — REUSE, здесь не дублируется);
  * invalid остаётся валидным исходом ТОЛЬКО для структурно битых ответов
    (bad type/unknown field/unknown id — fail-soft §50.35 не трогается).

Чистый модуль (0 LLM, без БД/сети/часов): вход не мутируется,
детерминированно, двойной прогон байт-идентичен. Δ DDL = 0.

Kill-switch ``SUMMARY_L1_CAPACITY_GUARD_ENABLED`` (env, default ON):
OFF → ``too_many_facts`` → invalid → fallback package (как сейчас,
бит-в-бит).
"""
from __future__ import annotations

import logging
import math
import re

from config.settings import settings

logger = logging.getLogger(__name__)

# ── Kill-switch (spec §8.2) ────────────────────────────────────────────────

def capacity_guard_enabled() -> bool:
    """``SUMMARY_L1_CAPACITY_GUARD_ENABLED`` (env-only, default ON; резолв
    per-call, никогда не бросает). OFF → прежний путь: переполнение
    контракта → whole-run invalid → fallback-пакет (бит-в-бит)."""
    try:
        return bool(getattr(settings, "SUMMARY_L1_CAPACITY_GUARD_ENABLED",
                            True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


# Developer bounds планировщика (§52; env, Δ каталога = 0).
def target_facts_per_chunk() -> int:
    """Целевая семантическая кардинальность ОДНОГО L1-чанка (output reserve
    планирования): ниже потолка 30 с запасом на merge-union. Default 24."""
    try:
        value = int(getattr(settings, "SUMMARY_L1_TARGET_FACTS_PER_CHUNK",
                            24))
    except (TypeError, ValueError):      # pragma: no cover - защитная ветка
        return 24
    return max(4, value)


def messages_per_fact() -> int:
    """Эвристика плотности: сколько сообщений «в среднем» дают один факт.
    Default 12 (разговорный чат: вопросы/шутки/болтовня не становятся
    фактами). Только planning-оценка, не контрактный лимит."""
    try:
        value = int(getattr(
            settings, "SUMMARY_L1_FACT_DENSITY_MESSAGES_PER_FACT", 12))
    except (TypeError, ValueError):      # pragma: no cover - защитная ветка
        return 12
    return max(1, value)


# ── Причины переполнения контракта (§51; repair-класс, не retryable) ───────

CAPACITY_REASONS: frozenset[str] = frozenset({
    "too_many_facts", "too_many_facts_total", "too_many_threads",
})

WS_RE = re.compile(r"\s+")


def _fact_key(text) -> str:
    """Stable-ID ключ факта (та же нормализация, что ``summary_l1_contract``
    / ``summary_semantic_reduction``: strip + casefold + схлопывание пробелов)."""
    return WS_RE.sub(" ", str(text or "").strip()).casefold()


def _topic_key(name) -> str:
    return WS_RE.sub(" ", str(name or "").strip()).casefold()


# ── §52: planning estimate ─────────────────────────────────────────────────

def estimate_expected_facts(rows) -> int:
    """Ожидаемая семантическая кардинальность окна (planning estimate §52).

    Компоненты: source size (message count) + reply density (ответы
    плотнее «болтовни» — чаще становятся фактами). Эвристика планирования:
    заниженная оценка означает просто меньше заранее нарезанных чанков, а
    переполнение ловит post-model repair — система остаётся корректной.
    """
    rows = [r for r in (rows or []) if r is not None]
    total = len(rows)
    if total == 0:
        return 0
    replies = 0
    for row in rows:
        value = None
        try:
            value = row["reply_to_id"]
        except (KeyError, TypeError, IndexError):
            value = getattr(row, "reply_to_id", None)
        if value is not None:
            replies += 1
    reply_ratio = min(1.0, replies / total) if total else 0.0
    density_factor = 1.0 + 0.5 * reply_ratio
    return max(1, math.ceil(total * density_factor / messages_per_fact()))


def plan_required_chunks(expected_facts: int) -> int:
    """Сколько L1-чанков требует output-кардинальность (§52): каждый чанк
    обязан иметь запас под ``MAX_FACTS_PER_THREAD`` на свою долю фактов."""
    target = target_facts_per_chunk()
    return max(1, math.ceil(max(0, expected_facts) / target))


def repartition_by_count(rows, parts: int, size_fn, limit: int) -> list:
    """Равномерная хронологическая нарезка на ``parts`` кусков с overlap=1
    (reply-continuity §122, дедуп на merge — тот же механизм, что у
    физической партиции). Каждый кусок не крупнее физического предшественника
    (``parts`` ≥ числа физических партиций); oversized-одиночное сообщение —
    свой чанк verbatim (§123). ``size_fn(row) → int`` — serialized-размер
    §92-элемента (тот же учёт, что ``pack_l1_input``)."""
    rows = list(rows or [])
    parts = max(1, int(parts))
    if not rows:
        return []
    if len(rows) <= 1 or parts == 1:
        return [rows]
    base = math.ceil(len(rows) / parts)
    partitions: list[list] = []
    current: list = []
    for row in rows:
        if current and len(current) >= base:
            # Граница по счётчику: куски мельче физических, входной бюджет
            # не нарушается. Overlap: последнее сообщение уходит в следующую
            # (reply-continuity, дедуп по stable ID на merge).
            overlap_row = current[-1]
            partitions.append(current)
            current = [overlap_row]
        current.append(row)
    if current:
        partitions.append(current)
    # Хвостовые мелкие куски (oversize-коррекции) сливаем назад — не плодим
    # лишних LLM-вызовов сверх плана.
    while len(partitions) > parts and len(partitions) > 1:
        tail = partitions.pop()
        partitions[-1].extend(tail)
    return partitions


# ── §51: deterministic capacity repair над §95-v2 payload ──────────────────

def repair_capacity_overflow(data):
    """Привести §95-v2 payload к структурным капам БЕЗ LLM и БЕЗ invalid.

    Порядок (§51): reduce duplicates → split semantic subthread → allocate
    output budget. Возвращает ``(payload | None, stats)``; ``None`` — вход
    не похож на payload (пустые треды после ремонта), вызывающий остаётся на
    прежнем invalid-пути. Вход НЕ мутируется. Детерминировано.

    stats (R17-safe числа): duplicates_merged, topics_deduped,
    threads_split, facts_dropped_budget, threads_after, facts_after.
    """
    stats = {"duplicates_merged": 0, "topics_deduped": 0, "threads_split": 0,
             "facts_dropped_budget": 0, "threads_after": 0, "facts_after": 0}
    if not isinstance(data, dict):
        return None, stats
    threads = data.get("threads")
    if not isinstance(threads, list):
        return None, stats

    # 1. Topic dedupe: темы с одинаковым нормализованным названием → одна
    #    (union message_ids, факты дальше схлопнет fact-dedupe).
    by_name: dict = {}
    threads_merged: list = []
    for thread in threads:
        if not isinstance(thread, dict):
            continue
        key = _topic_key(thread.get("topic"))
        target = by_name.get(key) if key else None
        if target is None:
            copy = {
                "thread_id": thread.get("thread_id"),
                "topic": thread.get("topic"),
                "message_ids": [m for m in (thread.get("message_ids") or [])
                                if isinstance(m, int)
                                and not isinstance(m, bool)],
                "facts": [dict(f) for f in (thread.get("facts") or [])
                          if isinstance(f, dict)],
            }
            threads_merged.append(copy)
            if key:
                by_name[key] = copy
            continue
        stats["topics_deduped"] += 1
        for mid in thread.get("message_ids") or []:
            if mid not in target["message_ids"]:
                target["message_ids"].append(mid)
        target["facts"].extend(dict(f) for f in (thread.get("facts") or [])
                               if isinstance(f, dict))

    # 2. Reduce duplicates: дедуп фактов по нормализованному тексту с union
    #    evidence (в рамках темы; many-to-many membership сохранён).
    for thread in threads_merged:
        seen: dict = {}
        kept: list = []
        for fact in thread["facts"]:
            key = _fact_key(fact.get("text"))
            evidence = [e for e in (fact.get("evidence_message_ids") or [])
                        if isinstance(e, int) and not isinstance(e, bool)]
            target = seen.get(key)
            if target is None:
                copy = {"text": fact.get("text"),
                        "evidence_message_ids": list(evidence)}
                kept.append(copy)
                if key:
                    seen[key] = copy
                continue
            stats["duplicates_merged"] += 1
            for eid in evidence:
                if eid not in target["evidence_message_ids"]:
                    target["evidence_message_ids"].append(eid)
        thread["facts"] = kept

    # 3. Split semantic subthread: тред > MAX_FACTS_PER_THREAD фактов →
    #    подсмыслы ≤ капа (первый несёт topic/thread_id verbatim + все
    #    message_ids, остальные — 'topic · N' + evidence своих фактов;
    #    пересечение membership разрешено схемой §95-v2).
    per_thread_cap = _max_facts_per_thread()
    split: list = []
    for thread in threads_merged:
        facts = thread["facts"]
        if len(facts) <= per_thread_cap:
            split.append(thread)
            continue
        stats["threads_split"] += 1
        topic = str(thread.get("topic") or "")
        base_thread_id = str(thread.get("thread_id") or "thread_001")
        chunks = [facts[i:i + per_thread_cap]
                  for i in range(0, len(facts), per_thread_cap)]
        for number, group in enumerate(chunks, start=1):
            if number == 1:
                split.append({"thread_id": base_thread_id, "topic": topic,
                              "message_ids": list(thread["message_ids"]),
                              "facts": [dict(f) for f in group]})
                continue
            sub_topic = f"{topic} · {number}"
            if len(sub_topic) > 200:      # TOPIC_MAX контракта §95
                sub_topic = sub_topic[:200]
            evidence: list = []
            for fact in group:
                for eid in fact.get("evidence_message_ids") or []:
                    if eid not in evidence:
                        evidence.append(eid)
            sub_thread_id = f"{base_thread_id[:56]}_p{number}"
            split.append({"thread_id": sub_thread_id, "topic": sub_topic,
                          "message_ids": evidence,
                          "facts": [dict(f) for f in group]})
    threads_merged = split

    # 4. Allocate output budget: тотальное переполнение MAX_FACTS_TOTAL →
    #    детерминированное вытеснение фактов с МИНИМУМОМ evidence (наименее
    #    подтверждённые первыми; tie — из более поздней темы/вхождения),
    #    чтобы не вынести одну тему целиком. Видимо счётчиком.
    total_cap = _max_facts_total()
    total = sum(len(t["facts"]) for t in threads_merged)
    if total > total_cap:
        ranked: list = []
        for t_index, thread in enumerate(threads_merged):
            for f_index, fact in enumerate(thread["facts"]):
                evidence_count = len(fact.get("evidence_message_ids") or [])
                ranked.append((evidence_count, t_index, f_index))
        # ASC по evidence; tie: более ПОЗДНИЕ темы/факты вылетают первыми
        # (сохраняем хронологически ранние якоря).
        ranked.sort(key=lambda item: (item[0], -item[1], -item[2]))
        drop = total - total_cap
        victims = {(t, f) for _e, t, f in ranked[:drop]}
        for t_index, thread in enumerate(threads_merged):
            if not any(t == t_index for t, _f in victims):
                continue
            kept = [fact for f_index, fact in enumerate(thread["facts"])
                    if (t_index, f_index) not in victims]
            stats["facts_dropped_budget"] += len(thread["facts"]) - len(kept)
            thread["facts"] = kept
        threads_merged = [t for t in threads_merged if t["facts"]]

    stats["threads_after"] = len(threads_merged)
    stats["facts_after"] = sum(len(t["facts"]) for t in threads_merged)
    if not threads_merged:
        return None, stats
    payload = {"schema_version": data.get("schema_version", 2),
               "threads": threads_merged,
               "unassigned_message_ids": list(
                   data.get("unassigned_message_ids") or [])}
    for key in ("response_mode", "cover_prompt"):
        if data.get(key):
            payload[key] = data[key]
    return payload, stats


def _max_facts_per_thread() -> int:
    """Кап фактов/тред — из контракта (``summary_l1_contract``), единый
    источник (spec §0.4: числа MAX_FACTS_* не меняются)."""
    try:
        from services.summary_l1_contract import MAX_FACTS_PER_THREAD
        return max(1, int(MAX_FACTS_PER_THREAD))
    except Exception:      # pragma: no cover - защитная ветка
        return 30


def _max_facts_total() -> int:
    try:
        from services.summary_l1_contract import MAX_FACTS_TOTAL
        return max(1, int(MAX_FACTS_TOTAL))
    except Exception:      # pragma: no cover - защитная ветка
        return 1000


# ── Логи (аддитивные, R17-safe: только числа) ──────────────────────────────

def log_capacity_plan(*, run_id, chat_id, source_messages, expected_facts,
                      physical_chunks, planned_chunks) -> None:
    logger.info(
        "L1_CAPACITY_PLAN | run_id=%s | chat_id=%s | source_messages=%d | "
        "expected_facts=%d | physical_chunks=%d | planned_chunks=%d",
        run_id or "none", chat_id, source_messages, expected_facts,
        physical_chunks, planned_chunks)


def log_capacity_repair(*, run_id, chat_id, stage, stats) -> None:
    logger.info(
        "L1_CAPACITY_REPAIR | run_id=%s | chat_id=%s | stage=%s | "
        "duplicates_merged=%d | topics_deduped=%d | threads_split=%d | "
        "facts_dropped_budget=%d | threads_after=%d | facts_after=%d",
        run_id or "none", chat_id, stage or "-",
        stats.get("duplicates_merged", 0), stats.get("topics_deduped", 0),
        stats.get("threads_split", 0), stats.get("facts_dropped_budget", 0),
        stats.get("threads_after", 0), stats.get("facts_after", 0))
