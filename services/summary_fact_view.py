"""ASAP 4.1 волна 3 (эпик `asap-4-1-durable-whole-window-summary`) —
FactPackage = DERIVED VIEW (T-4609, spec §2 B.3; ADR-1028-8 D4/AM-5).

Детерминированный синтез: SourceWindow (§92-items) + semantic map v1 →
FactPackage (fragments materialize; chronology; roster) — 0 LLM-вызовов.
Пакет понижен до derived view (analytics/debugging/Reviewer/memory/
fallback/compat; id-space валидации Writer-эвиденции): Writer НЕ зависит
от степени урезания пакета — он работает от полного окна
(`build_l2_source_input`). Потолки MAX_FACTS_PER_THREAD/MAX_FACTS_TOTAL
применяются здесь через существующий `repair_capacity_overflow`
(summary_l1_capacity.py, переиспользуется без изменений; §0.4 числа
не меняются).

Срезы (CAPACITY_OVERFLOW, иерархический Writer/Reviewer):
  * `slice_map_for_ids` — темы/события карты, относящиеся к набору id
    сегмента (структурные подсказки per-segment);
  * `slice_package_threads` — threads/unassigned пакета по набору id
    (сегментный fact view; id-space валидации сегментного черновика).

Чистый модуль; вход не мутируется; повторный прогон байт-идентичен; R17
(наружу только counts/коды). Δ DDL = 0; Δ каталога = 0.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import time

from services.summary_l1_capacity import repair_capacity_overflow
from services.summary_l1_semantic_map import MAP_SCHEMA_VERSION

logger = logging.getLogger(__name__)

FALLBACK_THREAD_ID = "thread_001"
FALLBACK_TOPIC_NAME = "Общий ход обсуждения"


# ── Доступ к полям строки §92 (тот же паттерн, что fact_package) ───────────

def _as_int(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _item_map(payload_items) -> dict:
    """TG message_id → §92-элемент (первое вхождение)."""
    items: dict = {}
    for item in payload_items or []:
        if not isinstance(item, dict):
            continue
        mid = _as_int(item.get("message_id"))
        if mid is None or mid in items:
            continue
        items[mid] = item
    return items


def _sort_key(item: dict) -> tuple:
    try:
        ts = int(item.get("timestamp") or 0)
    except (TypeError, ValueError):
        ts = 0
    mid = _as_int(item.get("message_id"))
    return (ts, mid if mid is not None else 0)


def _fragment_of(item: dict) -> dict:
    """Фрагмент пакета из §92-элемента (тот же набор полей, что
    fallback-пакет: author_id/display_name/timestamp/reply_to_id/text)."""
    fragment = {
        "message_id": _as_int(item.get("message_id")),
        "author_id": _as_int(item.get("author_id")),
        "display_name": item.get("display_name"),
        "timestamp": _as_int(item.get("timestamp")),
        "reply_to_id": _as_int(item.get("reply_to_id")),
        "text": item.get("text"),
    }
    # ASAP-4 волна D (§50.9): раздельные отношения kind
    # msg|reply|forward|quote из метаданных окна (без вымысла).
    if item.get("is_forward"):
        fragment["kind"] = "forward"
        source = item.get("forward_source")
        if source:
            fragment["forward_source"] = str(source)
    elif fragment.get("reply_to_id") is not None:
        fragment["kind"] = "reply"
    return fragment


@dataclasses.dataclass(frozen=True)
class FactViewResult:
    """Результат синтеза derived view (контракт FactPackageResult-семантики:
    ok/truncated deliverable; fail-closed причины)."""

    status: str
    package: dict | None
    reason: str | None
    metrics: dict
    budget: dict

    @property
    def deliverable(self) -> bool:
        return self.status in ("ok", "truncated") and self.package is not None

    @property
    def usable(self) -> bool:
        return self.deliverable


# ── Синтез FactPackage из SourceWindow + map (T-4609) ──────────────────────

def build_fact_view_from_map(map_payload, payload_items, *, chat_id=None,
                             correlation_id=None) -> FactViewResult:
    """SourceWindow + semantic map → FactPackage (derived view; 0 LLM).

    Материализация (детерминированно):
      * threads — темы карты ASC по первому сообщению; name = title,
        description = short_hint; chronology = message_ids ASC
        (timestamp из SourceWindow); fragments = §92-сообщения темы
        (author_id/display_name/reply/forward — без вымысла); facts = []
        (map v1 не несёт текстов фактов);
      * unassigned — как в карте;
      * потолки MAX_FACTS_PER_THREAD/MAX_FACTS_TOTAL — через существующий
        `repair_capacity_overflow` (для map-синтеза фактов нет → no-op,
        контракт применения потолков сохранён);
      * roster — build_participant_roster (вызывается при входе Writer).

    ``None``/пустая карта или пустое окно → fail-closed not_built
    (Writer продолжит от окна без fact_view; никогда не invalid-run)."""
    started = time.perf_counter()
    if not isinstance(map_payload, dict) \
            or not isinstance(map_payload.get("topics"), list):
        return FactViewResult(
            status="not_built", package=None, reason="map_missing",
            metrics={"reason": "map_missing"}, budget={})
    items = _item_map(payload_items)
    if not items:
        return FactViewResult(
            status="not_built", package=None, reason="source_empty",
            metrics={"reason": "source_empty"}, budget={})
    try:
        threads: list = []
        covered: set = set()
        for topic in map_payload.get("topics") or []:
            if not isinstance(topic, dict):
                continue
            ids = sorted({mid for mid in
                          (topic.get("message_ids") or [])
                          if isinstance(mid, int)
                          and not isinstance(mid, bool)
                          and mid in items},
                         key=lambda mid: _sort_key(items[mid]))
            if not ids:
                continue
            fragments = [_fragment_of(items[mid]) for mid in ids]
            threads.append({
                "thread_id": str(topic.get("topic_id") or FALLBACK_THREAD_ID),
                "name": str(topic.get("title") or ""),
                "description": str(topic.get("short_hint") or ""),
                "chronology": [
                    {"message_id": mid,
                     "timestamp": _as_int(items[mid].get("timestamp")),
                     "topic_ids": [str(topic.get("topic_id") or
                                       FALLBACK_THREAD_ID)]}
                    for mid in ids],
                "facts": [],
                "evidence_ids": list(ids),
                "fragments": fragments,
            })
            covered.update(ids)
        unassigned = sorted(
            {mid for mid in (map_payload.get("unassigned_message_ids") or [])
             if isinstance(mid, int) and not isinstance(mid, bool)
             and mid in items and mid not in covered})
        # Потолки MAX_FACTS_* — через существующий repair (§0.4): для
        # map-синтеза фактов НЕТ (facts=[]) → repair no-op; вызов идёт по
        # §95-проекции (repair копирует смежные поля ей известные), поэтому
        # реальные threads пакета не передаются напрямую.
        if all(not t["facts"] for t in threads):
            pass          # нет фактов — потолок тривиально соблюдён
        else:
            projection = {"threads": [
                {"thread_id": t["thread_id"],
                 "topic": t.get("name") or t["thread_id"],
                 "message_ids": list(t.get("evidence_ids") or []),
                 "facts": [dict(f) for f in (t.get("facts") or [])]}
                for t in threads]}
            repaired, _stats = repair_capacity_overflow(projection)
            if repaired is not None:
                # факты после ремонта возвращаются в threads (id-space не
                # меняется).
                repaired_by = {r.get("thread_id"): r for r in
                               repaired.get("threads") or []}
                for thread in threads:
                    fixed = repaired_by.get(thread["thread_id"])
                    if fixed is not None:
                        thread["facts"] = [dict(f) for f in
                                           (fixed.get("facts") or [])]

        estimated_tokens = len(json.dumps(
            {"threads": threads, "unassigned_message_ids": unassigned},
            ensure_ascii=False, separators=(",", ":")))
        service = {
            "response_mode": str(map_payload.get("response_mode") or ""),
            "cover_prompt": str(map_payload.get("cover_prompt") or ""),
            "package_grade": "semantic",
            "source_ref": "summary_source_window",
        }
        package = {
            "schema_version": 2,
            "status": "ok",
            "threads": threads,
            "unassigned_message_ids": unassigned,
            "service": service,
            "budget": {"kind": "tokens", "limit": 0, "estimated":
                       estimated_tokens, "fits": True},
        }
        duration_ms = (time.perf_counter() - started) * 1000.0
        logger.info(
            "FACT_VIEW_BUILT | run_id=%s | chat_id=%s | threads=%d | "
            "fragments=%d | unassigned=%d | duration_ms=%.0f",
            correlation_id or "none", chat_id if chat_id is not None
            else "-", len(threads),
            sum(len(t["fragments"]) for t in threads), len(unassigned),
            duration_ms)
        return FactViewResult(
            status="ok", package=package, reason="ok",
            metrics={"threads_count": len(threads),
                     "messages_count": len(covered) + len(unassigned),
                     "facts_count": 0,
                     "fragments_count": sum(len(t["fragments"])
                                            for t in threads),
                     "unassigned_count": len(unassigned),
                     "duration_ms": duration_ms},
            budget={"kind": "tokens", "limit": 0,
                    "estimated": estimated_tokens, "fits": True})
    except Exception:      # pragma: no cover - защитная ветка
        duration_ms = (time.perf_counter() - started) * 1000.0
        logger.warning(
            "FACT_VIEW_ERROR | run_id=%s | reason=internal_error",
            correlation_id or "none", exc_info=True)
        return FactViewResult(
            status="error", package=None, reason="internal_error",
            metrics={"reason": "internal_error",
                     "duration_ms": duration_ms}, budget={})


def fallback_view_for_items(payload_items) -> dict:
    """Сегментный/полный fallback fact view: одна тема chronology = ВСЕ
    §92-элементы ASC, fragments materialized, facts=[] (coverage честный
    по построению; Writer главным входом всё равно является окно)."""
    items = _item_map(payload_items)
    ordered = sorted(items.values(), key=_sort_key)
    ids = [_as_int(item.get("message_id")) for item in ordered]
    ids = [mid for mid in ids if mid is not None]
    thread = {
        "thread_id": FALLBACK_THREAD_ID,
        "name": FALLBACK_TOPIC_NAME,
        "description": "",
        "chronology": [
            {"message_id": mid,
             "timestamp": _as_int(items[mid].get("timestamp")),
             "topic_ids": [FALLBACK_THREAD_ID]} for mid in ids],
        "facts": [],
        "evidence_ids": list(ids),
        "fragments": [_fragment_of(items[mid]) for mid in ids],
    }
    estimated = len(json.dumps({"threads": [thread]},
                               ensure_ascii=False, separators=(",", ":")))
    return {
        "schema_version": 2, "status": "ok", "threads": [thread],
        "unassigned_message_ids": [],
        "service": {"response_mode": "", "cover_prompt": "",
                    "package_grade": "fallback_view",
                    "source_ref": "summary_source_window"},
        "budget": {"kind": "tokens", "limit": 0, "estimated": estimated,
                   "fits": True},
    }


def _fact_view_id_space(package) -> set:
    ids = set()
    for thread in (package or {}).get("threads") or []:
        if not isinstance(thread, dict):
            continue
        for entry in thread.get("chronology") or []:
            if isinstance(entry, dict):
                mid = entry.get("message_id")
                if isinstance(mid, int) and not isinstance(mid, bool):
                    ids.add(mid)
        for eid in thread.get("evidence_ids") or []:
            if isinstance(eid, int) and not isinstance(eid, bool):
                ids.add(eid)
    for mid in (package or {}).get("unassigned_message_ids") or []:
        if isinstance(mid, int) and not isinstance(mid, bool):
            ids.add(mid)
    return ids


def ensure_full_id_space(package, ids, fallback_thread_id="thread_999",
                         name="Сообщения вне тем (сегмент)") -> dict:
    """Гарантия: id-space сегментного пакета покрывает ВСЕ id сегмента
    (никогда не invalid_evidence от урезания derived view). Нехватающие
    id → детерминированный fallback-thread (chronology/fragments; факты
    не добавляются). Пакет НЕ мутируется."""
    package = dict(package) if isinstance(package, dict) else {}
    known = _fact_view_id_space(package)
    leftover = sorted({mid for mid in ids
                       if isinstance(mid, int) and not isinstance(mid, bool)}
                      - known)
    if not leftover:
        return package
    thread = {
        "thread_id": fallback_thread_id,
        "name": name,
        "description": "",
        "chronology": [{"message_id": mid, "timestamp": None,
                        "topic_ids": [fallback_thread_id]}
                       for mid in leftover],
        "facts": [],
        "evidence_ids": list(leftover),
        "fragments": [{"message_id": mid} for mid in leftover],
    }
    threads = list(package.get("threads") or [])
    threads.append(thread)
    package["threads"] = threads
    return package


# ── Срезы для CAPACITY_OVERFLOW (иерархический Writer/Reviewer) ────────────

def slice_map_for_ids(map_payload, ids) -> dict | None:
    """Темы/события/связи карты, пересекающиеся с набором id сегмента
    (сообщение может относиться к нескольким сегментам — пересечения
    нормальны; ASC, дедуп). ``None`` — для сегмента нет подсказок."""
    if not isinstance(map_payload, dict):
        return None
    id_set = {mid for mid in ids if isinstance(mid, int)
              and not isinstance(mid, bool)}
    topics = []
    for topic in map_payload.get("topics") or []:
        if not isinstance(topic, dict):
            continue
        seg_ids = [mid for mid in (topic.get("message_ids") or [])
                   if mid in id_set]
        if seg_ids:
            topics.append(dict(topic))
    events = []
    for event in map_payload.get("events") or []:
        if not isinstance(event, dict):
            continue
        seg_ids = [mid for mid in (event.get("message_ids") or [])
                   if mid in id_set]
        if seg_ids:
            events.append({"kind": event.get("kind"),
                           "message_ids": seg_ids})
    rels = []
    for rel in map_payload.get("relationships") or []:
        if not isinstance(rel, dict):
            continue
        seg_ids = [mid for mid in (rel.get("message_ids") or [])
                   if mid in id_set]
        if seg_ids:
            rels.append({"type": rel.get("type"), "message_ids": seg_ids,
                         "topic_ids": list(rel.get("topic_ids") or [])})
    if not topics and not events:
        return None
    sliced = {"schema_version": MAP_SCHEMA_VERSION, "topics": topics,
              "events": events,
              "unassigned_message_ids": []}
    if rels:
        sliced["relationships"] = rels
    return sliced


def slice_package_threads(package, ids) -> dict:
    """Сегментный fact view: threads пакета, отфильтрованные по набору id
    (chronology/fragments/facts — только элементы сегмента) + unassigned ∩
    ids. Служебные секции (service/budget) сохраняются как есть."""
    id_set = {mid for mid in ids if isinstance(mid, int)
              and not isinstance(mid, bool)}
    threads_out: list = []
    unassigned: list = []
    for thread in (package or {}).get("threads") or []:
        if not isinstance(thread, dict):
            continue
        chronology = [entry for entry in (thread.get("chronology") or [])
                      if isinstance(entry, dict)
                      and entry.get("message_id") in id_set]
        fragments = [f for f in (thread.get("fragments") or [])
                     if isinstance(f, dict) and f.get("message_id") in id_set]
        facts = [f for f in (thread.get("facts") or [])
                 if isinstance(f, dict)
                 and any(isinstance(e, int) and e in id_set
                         for e in (f.get("evidence_message_ids") or []))]
        evidence_ids = [eid for eid in (thread.get("evidence_ids") or [])
                        if eid in id_set]
        if not (chronology or fragments):
            continue
        threads_out.append({
            "thread_id": thread.get("thread_id"),
            "name": thread.get("name"),
            "description": thread.get("description"),
            "chronology": chronology, "facts": facts,
            "evidence_ids": evidence_ids, "fragments": fragments,
        })
    for mid in (package or {}).get("unassigned_message_ids") or []:
        if mid in id_set:
            unassigned.append(mid)
    sliced = dict(package) if isinstance(package, dict) else {}
    sliced = {k: v for k, v in sliced.items()
              if k not in ("threads", "unassigned_message_ids")}
    sliced["threads"] = threads_out
    sliced["unassigned_message_ids"] = unassigned
    return sliced


__all__ = [
    "FactViewResult", "FALLBACK_THREAD_ID", "FALLBACK_TOPIC_NAME",
    "build_fact_view_from_map", "ensure_full_id_space",
    "fallback_view_for_items", "slice_map_for_ids", "slice_package_threads",
]
