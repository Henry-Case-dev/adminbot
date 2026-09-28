"""ASAP-2 round1027 (ADR-1027-10 D2, spec контракт (b)) — deterministic repair
ответа L1: **отдельный чистый шаг между parse и validate**.

Инвариант владельца §6:2157–2190: «один выдуманный id не должен выбрасывать
весь L1 result» — неизвестные id удаляются детерминированно, evidence без
membership расширяет тред (evidence implies relation), пустые fact/topic
снимаются; валидатор остаётся строгим fail-closed checker'ом УЖЕ
отремонтированной структуры (partition-правила и unassigned-конфликт
мигрировали сюда из валидатора).

Модуль **чистый**: 0 LLM / 0 БД / 0 сети / 0 системных часов (по образцу
``summary_l1_contract``). Вход НЕ мутируется (копия). Порядок шагов строго
детерминирован (контракт (b) 1–7):

  1. ``threads[].message_ids``: id вне IdSpace → удалить (``unknown_ids_removed``);
  2. ``facts[].evidence_message_ids``: unknown → удалить; существующий, но НЕ
     в ``message_ids`` своего треда → ДОБАВИТЬ в ``message_ids``
     (``evidence_membership_added``; ``REASON_EVIDENCE_NOT_IN_THREAD`` живёт
     здесь, не в валидаторе);
  3. fact с пустым evidence после шагов 1–2 → удалить (``facts_removed``);
  4. тред с пустыми ``message_ids`` И пустыми ``facts`` → удалить
     (``topics_removed``); тред с сообщениями без фактов — СОХРАНЯЕТСЯ
     (хронология — материал для L2);
  5. ``unassigned_message_ids``: unknown → удалить; id, присутствующий в любом
     треде → убрать из unassigned (``unassigned_conflicts_resolved``;
     membership побеждает — ``REASON_UNASSIGNED_CONFLICT`` больше не fatal);
  6. ``overlapping_topic_memberships`` — число различных id в ≥2 тредах
     (информационно, §18);
  7. verdict ``useless`` по формуле Q3 (величины ПОСЛЕ repair):
     ``topics_after == 0 ∨ facts_after == 0 ∨
      unknown_ids_removed / max(ids_referenced_before, 1) > 0.5``;
     ``useless_reason`` ∈ {no_topics, no_facts, mass_unknown_ids}.

Все поля отчёта — int/bool (R17-safe; §18 событие ``L1_REPAIR``).
Kill-switch ``flags.summary_hybrid_l1_repair_enabled`` проверяется ВЫЗЫВАЮЩИМ
(run_l1): OFF → repair пропускается, валидатор v2 строгий как есть.
"""
from __future__ import annotations

import copy
import dataclasses

from services.summary_l1_contract import IdSpace


def _as_int(value):
    """Строгий int без bool-ловушки (та же политика, что в контракте §95)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


# Коды verdict «практически полностью бесполезен» (spec Q3; R17-safe).
USELESS_NO_TOPICS = "no_topics"
USELESS_NO_FACTS = "no_facts"
USELESS_MASS_UNKNOWN_IDS = "mass_unknown_ids"
# Граница «половина evidence уцелела — структура наполовину полезна,
# продолжаем» (§6:2188–2189): useless при строго большем отношении.
_MASS_UNKNOWN_RATIO = 0.5


@dataclasses.dataclass(frozen=True)
class RepairReport:
    """Счётчики детерминированного ремонта (все int/bool, R17-safe)."""

    unknown_ids_removed: int = 0
    facts_removed: int = 0
    topics_removed: int = 0
    evidence_membership_added: int = 0
    unassigned_conflicts_resolved: int = 0
    overlapping_topic_memberships: int = 0
    topics_before: int = 0
    topics_after: int = 0
    facts_before: int = 0
    facts_after: int = 0
    useless: bool = False
    useless_reason: str = ""

    def as_log_fields(self) -> dict:
        return dataclasses.asdict(self)


def _known_ids(data: dict) -> tuple[set, int]:
    """Различные id, на которые ссылается модель ДО repair (threads ∪
    facts[].evidence), и «ids_referenced_before» формулы Q3."""
    referenced: set = set()
    for thread in data.get("threads") or []:
        if not isinstance(thread, dict):
            continue
        for mid in thread.get("message_ids") or []:
            value = _as_int(mid)
            if value is not None:
                referenced.add(value)
        for fact in thread.get("facts") or []:
            if not isinstance(fact, dict):
                continue
            for mid in fact.get("evidence_message_ids") or []:
                value = _as_int(mid)
                if value is not None:
                    referenced.add(value)
    return referenced, len(referenced)


def repair_l1(data: dict, id_space: IdSpace) -> tuple[dict, RepairReport]:
    """Детерминированно починить распарсенный §95-v2 объект (вход НЕ мутирует).

    Возвращает ``(repaired, RepairReport)``. Структурно чужие элементы
    (не-dict треды/факты, не-списки полей) оставляются как есть — их отбракует
    валидатор (repair не делает решений о типе, только удаляет/добавляет id и
    снимает пустые элементы по шагам контракта (b)).
    """
    repaired = copy.deepcopy(data) if isinstance(data, dict) else {}
    referenced_before = _known_ids(data if isinstance(data, dict) else {})[1]

    threads = repaired.get("threads")
    if not isinstance(threads, list):
        threads = []
        repaired["threads"] = threads

    facts_before = 0
    for thread in threads:
        if isinstance(thread, dict) and isinstance(thread.get("facts"), list):
            facts_before += sum(1 for f in thread["facts"]
                                if isinstance(f, dict))

    unknown_ids_removed = 0
    evidence_membership_added = 0
    facts_removed = 0
    topics_removed = 0

    for thread in threads:
        if not isinstance(thread, dict):
            continue
        # Шаг 1: message_ids — unknown удалить (дубли внутри треда снимает
        # канонизация валидатора; здесь сохраняем порядок первого вхождения).
        raw_ids = thread.get("message_ids")
        message_ids: list = []
        if isinstance(raw_ids, list):
            for mid in raw_ids:
                value = _as_int(mid)
                if value is None:
                    continue
                if not id_space.contains(value):
                    unknown_ids_removed += 1
                    continue
                if value not in message_ids:
                    message_ids.append(value)
            thread["message_ids"] = message_ids
        else:
            message_ids = []
        # Шаг 2: evidence — unknown удалить; известный вне membership →
        # ДОБАВИТЬ в message_ids (evidence implies relation).
        raw_facts = thread.get("facts")
        kept_facts: list = []
        if isinstance(raw_facts, list):
            for fact in raw_facts:
                if not isinstance(fact, dict):
                    kept_facts.append(fact)
                    continue
                evidence = fact.get("evidence_message_ids")
                if not isinstance(evidence, list):
                    kept_facts.append(fact)
                    continue
                clean: list = []
                for eid in evidence:
                    value = _as_int(eid)
                    if value is None:
                        continue
                    if not id_space.contains(value):
                        unknown_ids_removed += 1
                        continue
                    if value not in clean:
                        clean.append(value)
                fact["evidence_message_ids"] = clean
                # Шаг 3: fact с пустым evidence после 1–2 → удалить.
                if not clean:
                    facts_removed += 1
                    continue
                # Расширение membership шага 2 (после оставления факта).
                for value in clean:
                    if value not in message_ids:
                        message_ids.append(value)
                        evidence_membership_added += 1
                kept_facts.append(fact)
            thread["facts"] = kept_facts
        # Шаг 4: тред без сообщений И без фактов → удалить (позже).
    # Удаление пустых тредов (шаг 4) — отдельным проходом, детерминированно.
    surviving_threads = []
    for thread in threads:
        if (isinstance(thread, dict)
                and not (thread.get("message_ids") in ([], None)
                         and thread.get("facts") in ([], None))):
            surviving_threads.append(thread)
        elif not isinstance(thread, dict):
            surviving_threads.append(thread)  # отбракует валидатор
    topics_removed = len(threads) - len(surviving_threads)
    repaired["threads"] = surviving_threads

    # Шаг 5: unassigned — unknown удалить; id из любого треда убрать
    # (membership побеждает).
    unassigned_conflicts_resolved = 0
    in_any_thread: set = set()
    for thread in surviving_threads:
        if isinstance(thread, dict) and isinstance(thread.get("message_ids"),
                                                   list):
            for mid in thread["message_ids"]:
                value = _as_int(mid)
                if value is not None:
                    in_any_thread.add(value)
    raw_unassigned = repaired.get("unassigned_message_ids")
    if isinstance(raw_unassigned, list):
        clean_unassigned: list = []
        for mid in raw_unassigned:
            value = _as_int(mid)
            if value is None:
                continue
            if not id_space.contains(value):
                unknown_ids_removed += 1
                continue
            if value in in_any_thread:
                unassigned_conflicts_resolved += 1
                continue
            if value not in clean_unassigned:
                clean_unassigned.append(value)
        repaired["unassigned_message_ids"] = clean_unassigned

    # Шаг 6: overlapping_topic_memberships — id в ≥2 тредах (информационно).
    counts: dict = {}
    for thread in surviving_threads:
        if isinstance(thread, dict) and isinstance(thread.get("message_ids"),
                                                   list):
            seen_here: set = set()
            for mid in thread["message_ids"]:
                value = _as_int(mid)
                if value is not None and value not in seen_here:
                    seen_here.add(value)
                    counts[value] = counts.get(value, 0) + 1
    overlapping = sum(1 for count in counts.values() if count >= 2)

    # Шаг 7: verdict useless (формула Q3; величины ПОСЛЕ repair).
    topics_after = sum(1 for thread in surviving_threads
                       if isinstance(thread, dict))
    facts_after = 0
    for thread in surviving_threads:
        if isinstance(thread, dict) and isinstance(thread.get("facts"), list):
            facts_after += sum(1 for fact in thread["facts"]
                               if isinstance(fact, dict))
    ratio_base = max(referenced_before, 1)
    useless = (topics_after == 0 or facts_after == 0
               or unknown_ids_removed / ratio_base > _MASS_UNKNOWN_RATIO)
    useless_reason = ""
    if useless:
        if topics_after == 0:
            useless_reason = USELESS_NO_TOPICS
        elif facts_after == 0:
            useless_reason = USELESS_NO_FACTS
        else:
            useless_reason = USELESS_MASS_UNKNOWN_IDS

    report = RepairReport(
        unknown_ids_removed=unknown_ids_removed,
        facts_removed=facts_removed,
        topics_removed=topics_removed,
        evidence_membership_added=evidence_membership_added,
        unassigned_conflicts_resolved=unassigned_conflicts_resolved,
        overlapping_topic_memberships=overlapping,
        topics_before=len(threads),
        topics_after=topics_after,
        facts_before=facts_before,
        facts_after=facts_after,
        useless=useless,
        useless_reason=useless_reason)
    return repaired, report
