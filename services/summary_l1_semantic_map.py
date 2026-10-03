"""ASAP 4.1 волна 3 (эпик `asap-4-1-durable-whole-window-summary`) — L1
semantic map v1: компактный выход кластеризатора БЕЗ source payload
(T-4607, spec §2 B.1; ADR-1028-8 D3).

Решение D3 (AM-1): L1 меняет выходной контракт с §95-v2
(threads/facts с текстами) на semantic map v1 — `topics[]` +
`events[]` + `relationships[]` (optional) + `unassigned_message_ids[]`
(ОБЯЗАТЕЛЕН) — **без текстов фактов/сообщений**: текст/author/timestamp/
reply materialize детерминированно из SummarySourceWindow (по
run_id/source_ref). Кардинальность «фактов» перестаёт быть выходным
измерением L1 → класс `too_many_facts*` из L1-валидации невозможен по
построению (не «поднят кап», а снято измерение). Числа капов
(§0.4) не меняются: MAX_FACTS_PER_THREAD=30/MAX_FACTS_TOTAL=1000 живут
в детерминированном синтезе FactPackage (summary_fact_view; T-4609).

Компактность-бюджеты (output control; developer deep env-only, D9):
  * ``topics ≤ MAX_THREADS (100)`` (summary_l1_contract — единый источник);
  * ``title ≤ TOPIC_MAX (200)``;
  * ``short_hint ≤ SUMMARY_L1_HINT_MAX_CHARS`` (default 160);
  * карта целиком ≤ ``SUMMARY_L1_MAP_MAX_TOKENS`` (default 6000).
Переполнение бюджета → **deterministic compaction** (merge мелких тем по
пересечению message_ids, дедуп, обрезка hints) + статус ``map_degraded``
в ``L1_RESULT`` — никогда не whole-run invalid и не «гильотина»:
sharding карты — fallback последней инстанции с полным сохранением
покрытия message_ids (все id сохраняются: в topics или unassigned).

**Чистый** модуль (0 LLM-вызовов, без БД/сети/системных часов);
детерминирован; вход не мутируется; повторный прогон байт-идентичен.

Kill-switch ``SUMMARY_L1_SEMANTIC_MAP_ENABLED`` (env-only, default ON;
резолв per-call, никогда не бросает): OFF → L1 держит контракт §95-v2
(``summary_l1_contract``) с прежней валидацией/``too_many_facts`` —
бит-в-бит 2.58.46.

R17: наружу только counts/коды/id; текстов сообщений/фактов в payload
нет (fixture-тест «в L1 output нет текстов сообщений», R6-B-002).
"""
from __future__ import annotations

import dataclasses
import logging

from config.settings import settings
from services.summary_l1_contract import (
    MAX_THREADS,
    TOPIC_MAX,
    IdSpace,
    REASON_BAD_TYPE,
    REASON_BAD_SCHEMA_VERSION,
    REASON_EMPTY_RESPONSE,
    REASON_INTERNAL_ERROR,
    REASON_INVALID_JSON,
    REASON_OK,
    REASON_UNKNOWN_FIELD,
    REASON_UNKNOWN_MESSAGE_ID,
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_INVALID,
    STATUS_OK,
    STATUS_TRUNCATED,
    USABLE_STATUSES,
    _as_int,
    service_fields,
)
from services.system2_handoff import parse_json_object
from services.token_counter import count_tokens

logger = logging.getLogger(__name__)

MAP_SCHEMA_VERSION = 1
EVENT_KIND_MAX = 32
RELATION_TYPE_MAX = 32
TOPIC_ID_MAX = 64
TOPIC_ID_PATTERN_MAX = 64
PARTICIPANT_MAX = 200
MAX_PARTICIPANTS_PER_TOPIC = 200

TOP_LEVEL_FIELDS: frozenset[str] = frozenset({
    "schema_version", "topics", "events", "relationships",
    "unassigned_message_ids", "response_mode", "cover_prompt",
})
TOPIC_FIELDS: frozenset[str] = frozenset({
    "topic_id", "title", "message_ids", "participants", "short_hint",
})
EVENT_FIELDS: frozenset[str] = frozenset({"kind", "message_ids"})
RELATION_FIELDS: frozenset[str] = frozenset(
    {"type", "message_ids", "topic_ids"})

TOPIC_ID_TEMPLATE = "topic_%03d"

# Reason-коды карты (R17-safe; регистрируются в mca_events.REASON_CODES).
REASON_MAP_OK = REASON_OK
REASON_MAP_COMPACTION_APPLIED = "map_compacted"
REASON_MAP_DEGRADED = "map_degraded"
REASON_MAP_SHARDED = "map_sharded"
REASON_SEMANTIC_MAP_UNAVAILABLE = "semantic_map_unavailable"

# Retryable-классы map-ответа (correction retry — одна попытка, как §15).
RETRYABLE_MAP_REASONS: frozenset[str] = frozenset({
    REASON_INVALID_JSON,
    REASON_EMPTY_RESPONSE,
    REASON_BAD_TYPE,
    REASON_UNKNOWN_FIELD,
    REASON_BAD_SCHEMA_VERSION,
    REASON_UNKNOWN_MESSAGE_ID,
})


# ── Kill-switch + бюджеты (env-only, Δ каталога = 0) ───────────────────────

def semantic_map_enabled() -> bool:
    """Kill-switch ``SUMMARY_L1_SEMANTIC_MAP_ENABLED`` (spec §2 B.1).
    OFF → L1 §95-v2 контракт (бит-в-бит 2.58.46). Никогда не бросает."""
    try:
        return bool(getattr(settings, "SUMMARY_L1_SEMANTIC_MAP_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def resolve_map_budgets(*, settings_obj=None) -> dict:
    """Бюджеты компактности semantic map (developer deep env-only; D9).
    Никогда не бросает (мусорные env → дефолты)."""
    st = settings_obj or settings
    try:
        hint_max = max(1, int(getattr(st, "SUMMARY_L1_HINT_MAX_CHARS", 160)))
    except (TypeError, ValueError):
        hint_max = 160
    try:
        map_tokens = max(1, int(getattr(st, "SUMMARY_L1_MAP_MAX_TOKENS",
                                        6000)))
    except (TypeError, ValueError):
        map_tokens = 6000
    return {
        "max_topics": MAX_THREADS,          # 100 (не меняется, §0.4)
        "title_max": TOPIC_MAX,             # 200 (не меняется, §0.4)
        "hint_max": hint_max,
        "map_max_tokens": map_tokens,
    }


# ── Результат валидации карты ──────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class MapResult:
    """Fail-closed результат semantic map (как ``L1Result``, но для map).

    ``payload`` — канонизированная карта (только при ok/truncated);
    ``degraded`` — честный флаг compaction/sharding (в ``L1_RESULT`` уходит
    как ``map_degraded``, никогда не маскируется ok); ``stats`` — числа
    compaction (R17-safe)."""

    status: str
    payload: dict | None
    reason: str | None
    topics_count: int
    events_count: int
    unassigned_count: int
    duration_ms: float = 0.0
    degraded: bool = False
    stats: dict = dataclasses.field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.status in USABLE_STATUSES and self.payload is not None


def map_result_error(reason: str, *, duration_ms: float = 0.0) -> MapResult:
    return MapResult(status=STATUS_ERROR, payload=None, reason=reason,
                     topics_count=0, events_count=0, unassigned_count=0,
                     duration_ms=duration_ms)


def map_result_invalid(reason: str, *, duration_ms: float = 0.0) -> MapResult:
    return MapResult(status=STATUS_INVALID, payload=None, reason=reason,
                     topics_count=0, events_count=0, unassigned_count=0,
                     duration_ms=duration_ms)


def map_result_empty(*, duration_ms: float = 0.0) -> MapResult:
    return MapResult(status=STATUS_EMPTY, payload=None, reason=None,
                     topics_count=0, events_count=0, unassigned_count=0,
                     duration_ms=duration_ms)


# ── Парсер (переиспользует политику system2_handoff) ───────────────────────

def parse_map_response(raw: str) -> tuple[dict | None, str]:
    """Строгий разбор ответа L1-map: ``(data | None, reason)`` (тот же
    ``parse_json_object``-канон, что §95-v2). Не бросает."""
    source = str(raw or "")
    if not source.strip():
        return None, REASON_EMPTY_RESPONSE
    data = parse_json_object(source)
    if not isinstance(data, dict):
        return None, REASON_INVALID_JSON
    return data, REASON_OK


# ── Валидация + канонизация map v1 ────────────────────────────────────────

def _valid_title(title, title_max: int):
    if not isinstance(title, str):
        return None
    if "\n" in title or "\r" in title:
        return None
    value = title.strip()
    if not value or len(value) > title_max:
        return None
    return value


def _valid_short_text(value, max_len: int):
    """Строка ≤ max_len, одна строка (без переносов); иначе None."""
    if value is None or not isinstance(value, str):
        return None
    if "\n" in value or "\r" in value:
        return None
    text = value.strip()
    if not text or len(text) > max_len:
        return None
    return text


def collect_unknown_map_ids(data, id_space: IdSpace, cap: int = 20) -> list:
    """Числовые message_id карты, отсутствующие в IdSpace (для
    correction-блока; в логи НЕ пишутся — R17)."""
    unknown: list = []
    try:
        for topic in (data or {}).get("topics") or []:
            if isinstance(topic, dict):
                for mid in topic.get("message_ids") or []:
                    value = _as_int(mid)
                    if value is not None and not id_space.contains(value) \
                            and value not in unknown:
                        unknown.append(value)
        for event in (data or {}).get("events") or []:
            if isinstance(event, dict):
                for mid in event.get("message_ids") or []:
                    value = _as_int(mid)
                    if value is not None and not id_space.contains(value) \
                            and value not in unknown:
                        unknown.append(value)
        for rel in (data or {}).get("relationships") or []:
            if isinstance(rel, dict):
                for mid in rel.get("message_ids") or []:
                    value = _as_int(mid)
                    if value is not None and not id_space.contains(value) \
                            and value not in unknown:
                        unknown.append(value)
        for mid in (data or {}).get("unassigned_message_ids") or []:
            value = _as_int(mid)
            if value is not None and not id_space.contains(value) \
                    and value not in unknown:
                unknown.append(value)
    except Exception:      # pragma: no cover - защитная ветка
        return unknown[:cap]
    return unknown[:cap]


def validate_semantic_map(data, id_space: IdSpace, *, duration_ms: float = 0.0
                          ) -> MapResult:
    """Проверить и канонизировать map v1 (строго, как §95-v2, но без фактов).

    Валидатор проверяет: структуру/типы/unknown-field (строго);
    ``schema_version == 1``; id-space (TG message_id); topic_id/title/
    participants лимиты-типы; kind ≤32; **unassigned_message_ids
    обязателен** (список, может быть пустым). Бюджеты компактности
    (topics≤100/title≤200/hint≤160/tokens≤map_max) НЕ роняют ответ —
    их снимает детерминированная compaction (``compact_semantic_map``).

    Не бросает; внутренняя ошибка → invalid ``internal_error``."""
    try:
        return _validate_map(data, id_space, duration_ms)
    except Exception:      # pragma: no cover - защитная ветка
        logger.warning("L1 map: internal error — fail-closed", exc_info=True)
        return map_result_invalid(REASON_INTERNAL_ERROR,
                                  duration_ms=duration_ms)


def _ids_in_space(raw_ids, id_space: IdSpace) -> list | None:
    """Канонизировать список id (dedup, порядок входа); None — bad_type
    или unknown id."""
    if not isinstance(raw_ids, list):
        return None
    ids: list = []
    for mid in raw_ids:
        value = _as_int(mid)
        if value is None:
            return None
        if not id_space.contains(value):
            return None
        if value not in ids:
            ids.append(value)
    return ids


def _validate_map(data, id_space: IdSpace, duration_ms: float) -> MapResult:
    if not isinstance(data, dict):
        return map_result_invalid(REASON_BAD_TYPE, duration_ms=duration_ms)

    if set(data) - TOP_LEVEL_FIELDS:
        return map_result_invalid(REASON_UNKNOWN_FIELD, duration_ms=duration_ms)

    response_mode, cover_prompt = service_fields(data)
    if not isinstance(data.get("schema_version"), int) \
            or isinstance(data.get("schema_version"), bool) \
            or data.get("schema_version") != MAP_SCHEMA_VERSION:
        return map_result_invalid(REASON_BAD_SCHEMA_VERSION,
                                  duration_ms=duration_ms)

    topics = data.get("topics")
    events = data.get("events")
    relationships = data.get("relationships")
    unassigned = data.get("unassigned_message_ids")
    if not isinstance(topics, list) or not isinstance(events, list) \
            or not isinstance(unassigned, list):
        return map_result_invalid(REASON_BAD_TYPE, duration_ms=duration_ms)
    if relationships is not None and not isinstance(relationships, list):
        return map_result_invalid(REASON_BAD_TYPE, duration_ms=duration_ms)

    canonical_topics: list[dict] = []
    for topic in topics:
        if not isinstance(topic, dict):
            return map_result_invalid(REASON_BAD_TYPE, duration_ms=duration_ms)
        if set(topic) - TOPIC_FIELDS:
            return map_result_invalid(REASON_UNKNOWN_FIELD,
                                      duration_ms=duration_ms)
        topic_id = topic.get("topic_id")
        if not isinstance(topic_id, str) or not topic_id.strip() \
                or len(topic_id) > TOPIC_ID_MAX:
            return map_result_invalid("invalid_topic_id",
                                      duration_ms=duration_ms)
        title = _valid_title(topic.get("title"), TOPIC_MAX)
        if title is None:
            return map_result_invalid("invalid_title",
                                      duration_ms=duration_ms)
        message_ids = _ids_in_space(topic.get("message_ids"), id_space)
        if message_ids is None:
            return map_result_invalid(REASON_UNKNOWN_MESSAGE_ID,
                                      duration_ms=duration_ms)
        raw_participants = topic.get("participants")
        if raw_participants is None:
            raw_participants = []
        if not isinstance(raw_participants, list):
            return map_result_invalid(REASON_BAD_TYPE, duration_ms=duration_ms)
        participants: list[str] = []
        for name in raw_participants:
            text = _valid_short_text(name, PARTICIPANT_MAX)
            if text is None:
                return map_result_invalid("invalid_participant",
                                          duration_ms=duration_ms)
            if text not in participants:
                participants.append(text)
        hint_raw = topic.get("short_hint")
        if hint_raw is None or hint_raw == "":
            hint = ""
        else:
            hint = _valid_short_text(hint_raw, 10**6)
            if hint is None:
                return map_result_invalid("invalid_short_hint",
                                          duration_ms=duration_ms)
        canonical_topics.append({
            "topic_id": topic_id, "title": title,
            "message_ids": message_ids, "participants": participants,
            "short_hint": hint,
        })

    canonical_events: list[dict] = []
    for event in events:
        if not isinstance(event, dict):
            return map_result_invalid(REASON_BAD_TYPE, duration_ms=duration_ms)
        if set(event) - EVENT_FIELDS:
            return map_result_invalid(REASON_UNKNOWN_FIELD,
                                      duration_ms=duration_ms)
        kind = event.get("kind")
        if not isinstance(kind, str) or not kind.strip() \
                or len(kind) > EVENT_KIND_MAX:
            return map_result_invalid("invalid_event_kind",
                                      duration_ms=duration_ms)
        message_ids = _ids_in_space(event.get("message_ids"), id_space)
        if message_ids is None:
            return map_result_invalid(REASON_UNKNOWN_MESSAGE_ID,
                                      duration_ms=duration_ms)
        canonical_events.append({"kind": kind.strip(),
                                 "message_ids": message_ids})

    canonical_rels: list[dict] = []
    for rel in relationships or []:
        if not isinstance(rel, dict):
            return map_result_invalid(REASON_BAD_TYPE, duration_ms=duration_ms)
        if set(rel) - RELATION_FIELDS:
            return map_result_invalid(REASON_UNKNOWN_FIELD,
                                      duration_ms=duration_ms)
        rel_type = rel.get("type")
        if not isinstance(rel_type, str) or not rel_type.strip() \
                or len(rel_type) > RELATION_TYPE_MAX:
            return map_result_invalid("invalid_relationship_type",
                                      duration_ms=duration_ms)
        message_ids = _ids_in_space(rel.get("message_ids"), id_space)
        if message_ids is None:
            return map_result_invalid(REASON_UNKNOWN_MESSAGE_ID,
                                      duration_ms=duration_ms)
        raw_topic_ids = rel.get("topic_ids")
        if raw_topic_ids is None:
            raw_topic_ids = []
        if not isinstance(raw_topic_ids, list):
            return map_result_invalid(REASON_BAD_TYPE, duration_ms=duration_ms)
        topic_ids: list[str] = []
        for tid in raw_topic_ids:
            text = _valid_short_text(tid, TOPIC_ID_MAX)
            if text is None:
                return map_result_invalid("invalid_topic_id",
                                          duration_ms=duration_ms)
            if text not in topic_ids:
                topic_ids.append(text)
        canonical_rels.append({"type": rel_type.strip(),
                               "message_ids": message_ids,
                               "topic_ids": topic_ids})

    unassigned_ids: list = []
    for mid in unassigned:
        value = _as_int(mid)
        if value is None:
            return map_result_invalid(REASON_BAD_TYPE, duration_ms=duration_ms)
        if not id_space.contains(value):
            return map_result_invalid(REASON_UNKNOWN_MESSAGE_ID,
                                      duration_ms=duration_ms)
        if value not in unassigned_ids:
            unassigned_ids.append(value)

    # Канонизация: сортировка id ASC (по sort_key id-space); темы — ASC по
    # первому сообщению; перенумерация topic_id; дедуп тем по пересечению
    # message_ids (compaction-семантика D3; счетчик — stats).
    mentioned = {mid for t in canonical_topics for mid in t["message_ids"]}
    mentioned.update(mid for e in canonical_events for mid in
                     e["message_ids"])
    mentioned.update(unassigned_ids)
    auto_added = sorted((mid for mid in id_space.ids if mid not in mentioned),
                        key=id_space.sort_key)
    unassigned_ids = sorted(set(unassigned_ids) | set(auto_added),
                            key=id_space.sort_key)

    canonical_topics.sort(
        key=lambda t: id_space.sort_key(t["message_ids"][0])
        if t["message_ids"] else (0, 0))
    topics_out = []
    for number, topic in enumerate(canonical_topics, start=1):
        topics_out.append({
            "topic_id": TOPIC_ID_TEMPLATE % number,
            "title": topic["title"],
            "message_ids": sorted(topic["message_ids"],
                                  key=id_space.sort_key),
            "participants": topic["participants"],
            "short_hint": topic["short_hint"],
        })
    events_out = canonical_events
    rels_out = canonical_rels

    payload = {
        "schema_version": MAP_SCHEMA_VERSION,
        "topics": topics_out,
        "events": events_out,
        "unassigned_message_ids": unassigned_ids,
    }
    if rels_out:
        payload["relationships"] = rels_out
    if response_mode:
        payload["response_mode"] = response_mode
    if cover_prompt:
        payload["cover_prompt"] = cover_prompt

    if not topics_out and not events_out:
        return MapResult(status=STATUS_EMPTY, payload=None, reason=None,
                         topics_count=0, events_count=0,
                         unassigned_count=len(unassigned_ids),
                         duration_ms=duration_ms)

    logger.info(
        "L1_MAP_VALIDATED | topics=%d | events=%d | unassigned=%d",
        len(topics_out), len(events_out), len(unassigned_ids))
    return MapResult(status=STATUS_OK, payload=payload,
                     reason=REASON_MAP_OK, topics_count=len(topics_out),
                     events_count=len(events_out),
                     unassigned_count=len(unassigned_ids),
                     duration_ms=duration_ms)


# ── Бюджет карты + deterministic compaction (D3) ───────────────────────────

def map_payload_tokens(payload) -> int:
    """Токены канонизированной карты (тот же счётчик, что L1/L2 вход)."""
    import json
    try:
        return count_tokens(json.dumps(payload, ensure_ascii=False,
                                       separators=(",", ":")))
    except Exception:      # pragma: no cover - защитная ветка
        return 0


def _trim_to_limit(text: str, limit: int) -> str:
    """Детерминированная обрезка короткой метки до лимита (по границе
    слова, без «висячих» разделителей)."""
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space >= int(limit * 0.5):
        cut = cut[:space]
    return cut.strip()


def compact_semantic_map(payload, *, id_space: IdSpace,
                         budgets: dict | None = None) -> tuple[
        dict | None, dict, bool]:
    """Deterministic compaction переполненной карты (D3; никогда не
    whole-run invalid и не «гильотина»).

    Лестница (детерминированная):
      1. обрезка title (≤ TOPIC_MAX — уже валидатором, защита от смены
         бюджета env) и short_hint до нижней границы;
      2. topics > MAX_THREADS → merge тем по пересечению message_ids
         (union ids/participants; hint — от темы с наибольшим покрытием),
         затем, если пересечений не хватает, — pairwise-merge самых
         мелких тем (меньше всего message_ids; tie — порядок темы);
      3. tokens > map_max_tokens → снять relationships (optional) → снять
         hints → merge мелких тем до влезания.
    Все message_ids СОХРАНЯЮТСЯ (merge — union; последний рубеж: id
    остаются в карте, а не выбрасываются). Признак деградации — ``True``
    → статус ``map_degraded`` в ``L1_RESULT`` (честно, не ok-маска).

    Возвращает ``(payload | None, stats, degraded)``; ``None`` — вход не
    похож на карту. Вход НЕ мутируется; повторный прогон байт-идентичен."""
    stats = {"hints_trimmed": 0, "topics_merged": 0,
             "relationships_dropped": 0, "hints_cleared": 0}
    if not isinstance(payload, dict) or not isinstance(
            payload.get("topics"), list):
        return None, stats, False
    budgets = budgets or resolve_map_budgets()
    topics = [dict(t) for t in payload["topics"] if isinstance(t, dict)]
    if not topics:
        return None, stats, False

    degraded = False

    # 1. Обрезка hints (title уже ≤ TOPIC_MAX по валидатору; подстраховка).
    hint_max = int(budgets["hint_max"])
    for topic in topics:
        hint = str(topic.get("short_hint") or "")
        if len(hint) > hint_max:
            topic["short_hint"] = _trim_to_limit(hint, hint_max)
            stats["hints_trimmed"] += 1
            degraded = True
        title = str(topic.get("title") or "")
        if len(title) > int(budgets["title_max"]):
            topic["title"] = _trim_to_limit(title, int(budgets["title_max"]))
            stats["hints_trimmed"] += 1
            degraded = True

    def _merge_pair(a: dict, b: dict) -> dict:
        ids = list(a.get("message_ids") or [])
        for mid in b.get("message_ids") or []:
            if mid not in ids:
                ids.append(mid)
        participants = list(a.get("participants") or [])
        for name in b.get("participants") or []:
            if name not in participants:
                participants.append(name)
        hint_a = str(a.get("short_hint") or "")
        hint_b = str(b.get("short_hint") or "")
        return {
            "topic_id": a.get("topic_id") or b.get("topic_id"),
            "title": (str(a.get("title") or "") or str(b.get("title") or "")),
            "message_ids": ids,
            "participants": participants,
            "short_hint": hint_a if len(hint_a) >= len(hint_b) else hint_b,
        }

    max_topics = int(budgets["max_topics"])
    if len(topics) > max_topics:
        degraded = True
        # merge по пересечению message_ids (транзитивно; union).
        merged: list[dict] = []
        for topic in topics:
            ids = set(topic.get("message_ids") or [])
            target = None
            for candidate in merged:
                if ids & set(candidate.get("message_ids") or []):
                    target = candidate
                    break
            if target is None:
                merged.append(topic)
                continue
            combined = _merge_pair(target, topic)
            target.update(combined)
            stats["topics_merged"] += 1
        topics = merged
        # Пересечений не хватило → pairwise-merge самых мелких.
        while len(topics) > max_topics:
            order = sorted(
                range(len(topics)),
                key=lambda i: (len(topics[i].get("message_ids") or []),
                               str(topics[i].get("topic_id") or "")))
            a, b = order[0], order[1]
            pair = sorted((a, b))
            combined = _merge_pair(topics[pair[0]], topics[pair[1]])
            topics[pair[0]] = combined
            topics.pop(pair[1])
            stats["topics_merged"] += 1

    result = dict(payload)
    result["topics"] = topics

    # 3. Token-бюджет карты.
    map_max = int(budgets["map_max_tokens"])
    if map_payload_tokens(result) > map_max:
        degraded = True
        if result.get("relationships"):
            stats["relationships_dropped"] = len(result["relationships"])
            result = dict(result)
            result.pop("relationships", None)
        if map_payload_tokens(result) > map_max:
            # снять hints (метаданные ≤160 — дешёвый выигрыш).
            stripped = []
            for topic in result["topics"]:
                topic = dict(topic)
                if topic.get("short_hint"):
                    stats["hints_cleared"] += 1
                topic["short_hint"] = ""
                stripped.append(topic)
            result = dict(result)
            result["topics"] = stripped
        while map_payload_tokens(result) > map_max and len(result["topics"]) > 1:
            order = sorted(
                range(len(result["topics"])),
                key=lambda i: (len(result["topics"][i].get(
                    "message_ids") or []),
                    str(result["topics"][i].get("topic_id") or "")))
            a, b = sorted((order[0], order[1]))
            combined = _merge_pair(result["topics"][a], result["topics"][b])
            topics_new = list(result["topics"])
            topics_new[a] = combined
            topics_new.pop(b)
            result = dict(result)
            result["topics"] = topics_new
            stats["topics_merged"] += 1

    result["schema_version"] = MAP_SCHEMA_VERSION
    if degraded:
        stats["reason"] = REASON_MAP_COMPACTION_APPLIED
    return result, stats, degraded


def map_correction_block(reason: str, *, unknown_ids: list,
                         useless_reason: str = "") -> str:
    """Correction-блок map-режима (контракт (c)-семантика): append к
    исходному user-контенту; только id/схема, без контента (R17)."""
    lines = [f"ПРЕДЫДУЩИЙ ОТВЕТ ОТКЛОНЁН: {reason}."]
    if unknown_ids:
        lines.append(
            "неизвестные message_id ["
            + ", ".join(str(value) for value in unknown_ids)
            + "]. Используй ТОЛЬКО message_id из входных данных. "
              "Не выдумывай идентификаторы. Do not invent message ids.")
    if reason in (REASON_INVALID_JSON, REASON_EMPTY_RESPONSE,
                  REASON_BAD_SCHEMA_VERSION, REASON_BAD_TYPE,
                  REASON_UNKNOWN_FIELD):
        lines.append(
            "верни СТРОГО валидный JSON-объект по схеме semantic map v1 "
            "(schema_version: 1), без текста вокруг.")
    else:
        lines.append(
            "верни строго валидный JSON-объект semantic map v1 "
            "(schema_version: 1): topics[] ({topic_id, title ≤200, "
            "message_ids[], participants[], short_hint ≤160}), events[] "
            "({kind ≤32, message_ids[]}), relationships[] (optional), "
            "unassigned_message_ids[] — обязательное поле. Никаких текстов "
            "сообщений и фактов в выходе.")
    lines.append("Верни исправленный JSON.")
    return "\n".join(lines)


# ── Merge map-payload'ов + minimal map (T-4608, spec §2 B.2) ───────────────

def merge_map_payloads(payloads: list) -> dict | None:
    """Детерминированный merge нескольких semantic map (без LLM):

      * темы с пересечением message_ids → одна (union ids/participants;
        title/hint — от темы с наибольшим покрытием);
      * events — merge по kind (union message_ids);
      * relationships — merge по type (union ids/topic_ids);
      * unassigned — union − упомянутые в темах;
      * перенумерация ``topic_id``, ASC-порядок по первому сообщению.

    Никогда не бросает; пустой вход → ``None``."""
    topics: list[dict] = []
    events: list[dict] = []
    rels: list[dict] = []
    service = {}
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        for topic in payload.get("topics") or []:
            if isinstance(topic, dict) and topic.get("title"):
                topics.append(topic)
        for event in payload.get("events") or []:
            if isinstance(event, dict) and event.get("kind"):
                events.append(event)
        for rel in payload.get("relationships") or []:
            if isinstance(rel, dict) and rel.get("type"):
                rels.append(rel)
        for key in ("response_mode", "cover_prompt"):
            if payload.get(key) and key not in service:
                service[key] = payload[key]
    if not topics and not events:
        unassigned: list[int] = []
        for payload in payloads or []:
            if not isinstance(payload, dict):
                continue
            for mid in payload.get("unassigned_message_ids") or []:
                if isinstance(mid, int) and mid not in unassigned:
                    unassigned.append(mid)
        if not unassigned:
            return None
        return {"schema_version": MAP_SCHEMA_VERSION, "topics": [],
                "events": [],
                "unassigned_message_ids": sorted(unassigned)}

    def _key_of(mid) -> int:
        return mid if isinstance(mid, int) and not isinstance(mid, bool) else 0

    merged: list[dict] = []
    for topic in topics:
        ids = {_key_of(mid) for mid in (topic.get("message_ids") or [])}
        target = None
        for candidate in merged:
            if ids & {mid for mid in candidate["message_ids"]}:
                target = candidate
                break
        if target is None:
            merged.append({
                "title": str(topic.get("title") or ""),
                "message_ids": sorted(ids),
                "participants": [str(p) for p in
                                 (topic.get("participants") or [])],
                "short_hint": str(topic.get("short_hint") or ""),
            })
            continue
        target["message_ids"] = sorted(set(target["message_ids"]) | ids)
        for name in topic.get("participants") or []:
            if name not in target["participants"]:
                target["participants"].append(str(name))
        if len(str(topic.get("short_hint") or "")) > len(
                target["short_hint"]):
            target["short_hint"] = str(topic.get("short_hint") or "")
    merged.sort(key=lambda t: (t["message_ids"][0] if t["message_ids"] else 0))

    events_out: list[dict] = []
    by_kind: dict[str, dict] = {}
    for event in events:
        kind = str(event.get("kind") or "").strip()[:EVENT_KIND_MAX]
        item = by_kind.get(kind)
        if item is None:
            item = {"kind": kind, "message_ids": []}
            by_kind[kind] = item
            events_out.append(item)
        for mid in event.get("message_ids") or []:
            value = _key_of(mid)
            if value not in item["message_ids"]:
                item["message_ids"].append(value)

    rels_out: list[dict] = []
    by_type: dict[str, dict] = {}
    for rel in rels:
        rel_type = str(rel.get("type") or "").strip()[:RELATION_TYPE_MAX]
        item = by_type.get(rel_type)
        if item is None:
            item = {"type": rel_type, "message_ids": [], "topic_ids": []}
            by_type[rel_type] = item
            rels_out.append(item)
        for mid in rel.get("message_ids") or []:
            value = _key_of(mid)
            if value not in item["message_ids"]:
                item["message_ids"].append(value)
        for tid in rel.get("topic_ids") or []:
            text = str(tid or "").strip()
            if text and text not in item["topic_ids"]:
                item["topic_ids"].append(text)

    mentioned: set[int] = set()
    for topic in merged:
        mentioned.update(topic["message_ids"])
    for event in events_out:
        mentioned.update(event["message_ids"])
    unassigned = []
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        for mid in payload.get("unassigned_message_ids") or []:
            if isinstance(mid, int) and not isinstance(mid, bool) \
                    and mid not in mentioned and mid not in unassigned:
                unassigned.append(mid)

    topics_out = []
    for number, topic in enumerate(merged, start=1):
        topics_out.append({
            "topic_id": TOPIC_ID_TEMPLATE % number,
            "title": topic["title"],
            "message_ids": topic["message_ids"],
            "participants": topic["participants"],
            "short_hint": topic["short_hint"],
        })
    payload_out = {
        "schema_version": MAP_SCHEMA_VERSION,
        "topics": topics_out,
        "events": events_out,
        "unassigned_message_ids": sorted(unassigned),
    }
    if rels_out:
        payload_out["relationships"] = rels_out
    payload_out.update(service)
    return payload_out


def minimal_map_for_rows(payload_items, *, seg_index: int = 1,
                         title: str | None = None) -> dict | None:
    """Deterministic minimal map непокрытого сегмента (T-4608, spec §2 B.2;
    ADR-1028-8 D3.4): структурная заготовка из ledger — хронология/
    участники БЕЗ LLM; полный набор message_ids сегмента сохраняется
    (никогда не превращать 3/4 success в 0/839).

    ``payload_items`` — §92-элементы сегмента. ``None`` — нет ids."""
    ids: list[int] = []
    participants: list[str] = []
    for item in payload_items or []:
        if not isinstance(item, dict):
            continue
        mid = _as_int(item.get("message_id"))
        if mid is None:
            continue
        if mid not in ids:
            ids.append(mid)
        name = item.get("display_name")
        if isinstance(name, str) and name.strip() and name not in participants:
            participants.append(name)
    if not ids:
        return None
    return {
        "schema_version": MAP_SCHEMA_VERSION,
        "topics": [{
            "topic_id": TOPIC_ID_TEMPLATE % seg_index,
            "title": title or f"Сегмент {seg_index} (структурная заготовка)",
            "message_ids": ids,
            "participants": participants,
            "short_hint": "",
        }],
        "events": [],
        "unassigned_message_ids": [],
    }


__all__ = [
    "MAP_SCHEMA_VERSION", "MapResult", "EVENT_KIND_MAX",
    "REASON_MAP_OK", "REASON_MAP_COMPACTION_APPLIED", "REASON_MAP_DEGRADED",
    "REASON_MAP_SHARDED", "REASON_SEMANTIC_MAP_UNAVAILABLE",
    "RETRYABLE_MAP_REASONS", "TOPIC_ID_TEMPLATE",
    "semantic_map_enabled", "resolve_map_budgets", "parse_map_response",
    "validate_semantic_map", "compact_semantic_map", "map_payload_tokens",
    "collect_unknown_map_ids", "map_correction_block",
    "map_result_invalid", "map_result_empty", "map_result_error",
    "merge_map_payloads", "minimal_map_for_rows",
]
