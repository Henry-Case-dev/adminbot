"""S4 round1026 (ADR-1026-6 D1–D6) + ASAP-2 round1027 (ADR-1027-10 D10/D4) —
«Пакет фактов §96» v2 (вход L2) + deterministic fallback-пакет LEVEL-2.

**Чистый** модуль (0 LLM-вызовов, без БД/сети/системных часов бизнес-логики):
из валидированного ``L1Result`` (§95-v2, S3) и §92-payload
(``summary_l1_clusterizer.build_l1_payload``) детерминированно собирает
пакет фактов для L2 (§96/§12): на каждую тему — название, описание, хронологию,
факты, подтверждающие ID и исходные фрагменты с ПОЛНЫМ авторским контекстом.
Весь сырой лог повторно НЕ передаётся; «доказательства» не генерируются.

Контракт пакета ``FactPackage`` v2 (контракт (h)):
  * топ-уровень ровно: ``{schema_version: 2, status, threads[],
    unassigned_message_ids[], service{response_mode, cover_prompt},
    budget{kind, limit, estimated, fits}}``;
  * тема ровно: ``{thread_id, name, description, chronology[], facts[],
    evidence_ids[], fragments[]}``;
  * ``fragments`` — v2: ``{message_id, author_id, display_name, timestamp,
    reply_to_id, text}`` (§12: рассказчик видит, «кто что сказал / кто кому
    отвечал»; ``reply_to_id`` = null без ответа); внутренняя техническая
    metadata (chat_id/DB id/message_type/mentions/budget/service/веса) НЕ
    тащится (§12:2397);
  * ``chronology`` = ASC ``(timestamp, message_id)`` + ``topic_ids[]`` —
    many-to-many карта всех тем, содержащих сообщение (производная графа, D1);
  * membership-пересечения тем больше НЕ рвут сборку
    (``message_in_multiple_threads`` УДАЛЁН; дедуп фрагментов между темами не
    выполняется — локальность важнее экономии, D10; пределы — капы 30/500 +
    бюджет); ``unassigned_conflict`` — только defense-in-depth (чинит repair);
  * ``name`` = ``topic`` verbatim; ``description`` = детерминированная
    агрегация ``facts[].text`` (дедуп/схлопывание/кап ``DESCRIPTION_MAX``);
  * фиксированный порядок ключей; двойной прогон байт-идентичен.

LEVEL-2 fallback (контракт (i), §8:2243–2260): ``build_fallback_package`` —
детерминированный пакет «Общий ход обсуждения» (0 LLM) из filtered §92-
сообщений, когда L1 непригоден ЛЮБАЯ причина; chronology = все сообщения ASC,
fragments = v2 (author+text+reply), статус ok/truncated (обязан проходить
deliverability-гейт ``run_l2``) → L2 вызывается в любом случае.

Бюджет L2-входа — hybrid-ключи ``limits.summary_hybrid_context_*``
(ASAP-2 §11/D7; единая точка ``resolve_hybrid_context_budget`` +
L2-output-reserve, контракт (g)). Legacy-ключи НЕ читаются. Усечение:
фрагменты (старые первыми) → ``description`` → целые темы; любое вытеснение →
``truncated`` + ``skipped_ids``/WARN.

Fail-closed (D5): ``empty``/``invalid``/``error`` → ``threads=[]`` и в L2 НЕ
передаётся (§95/§106 — для ОСНОВНОГО пакета; L1-непригодность обрабатывает
LEVEL-2 вызывающий контур); нет ``usable``/``payload`` → ``not_built``.
ID — TG ``message_id`` (§92/§95); DB ``id`` в публичное поле не попадает.
Висячие/фабрикованные ссылки → ``invalid``. Вход не мутируется.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
import time

from config.settings import settings
from services.summary_l1_contract import (
    STATUS_EMPTY,
    STATUS_ERROR,
    STATUS_INVALID,
    STATUS_OK,
    STATUS_TRUNCATED,
    build_id_space,
)
from services.summary_hybrid_budget import (
    hybrid_input_budget,
    hybrid_output_reserve_tokens,
    resolve_hybrid_context_budget,
)
from services.token_counter import count_tokens

logger = logging.getLogger(__name__)

MODULE = "summary"
STEP = "fact_package"

# ── Схема пакета v2 (ASAP-2 контракт (h)) ──────────────────────────────────

SCHEMA_VERSION = 2
# Тема LEVEL-2 fallback-пакета (§8:2252): одна хронологическая тема.
FALLBACK_THREAD_ID = "thread_001"
FALLBACK_TOPIC_NAME = "Общий ход обсуждения"

TOP_LEVEL_FIELDS: tuple = ("schema_version", "status", "threads",
                           "unassigned_message_ids", "service", "budget")
THREAD_FIELDS: tuple = ("thread_id", "name", "description", "chronology",
                        "facts", "evidence_ids", "fragments")

# Статусы FactPackageResult: ok/truncated — доставляемые в L2; empty/invalid/
# error — fail-closed (threads=[], в L2 не идут, §95/§106); not_built — пакет
# вообще не построен (нет usable-результата L1).
STATUS_NOT_BUILT = "not_built"
DELIVERABLE_STATUSES: frozenset = frozenset({STATUS_OK, STATUS_TRUNCATED})
_KNOWN_L1_STATUSES: frozenset = frozenset(
    {STATUS_OK, STATUS_TRUNCATED, STATUS_EMPTY, STATUS_INVALID, STATUS_ERROR})

# Коды причин (R17-safe: только коды, без контента).
# ASAP-2 v2: REASON_MESSAGE_IN_MULTIPLE_THREADS УДАЛЁН (контракт (a)/(h)):
# пересечение membership — норма many-to-many, сборку не рвёт.
REASON_OK = "ok"
REASON_EMPTY = "empty"
REASON_NO_RESULT = "no_result"
REASON_UNKNOWN_STATUS = "unknown_status"
REASON_PAYLOAD_MISSING = "payload_missing"
REASON_BAD_INPUT = "bad_type"
REASON_MISSING_SOURCE = "missing_source"
REASON_UNKNOWN_MESSAGE_ID = "unknown_message_id"
REASON_EVIDENCE_NOT_IN_THREAD = "evidence_not_in_thread"
REASON_UNASSIGNED_CONFLICT = "unassigned_conflict"
REASON_BUDGET_EMPTY = "budget_empty"
REASON_INTERNAL_ERROR = "internal_error"

# ── Лимиты композиции (константы модуля, Δ каталога = 0) ───────────────────

DESCRIPTION_MAX = 500
DESCRIPTION_SEPARATOR = " · "
FRAGMENT_MAX_CHARS = 1000
MAX_FRAGMENTS_PER_THREAD = 30
MAX_FRAGMENTS_TOTAL = 500

# §5.6/ASAP-2 D7: бюджет — hybrid-ключи `limits.summary_hybrid_context_*`
# (единая точка `summary_hybrid_budget`); токенный дефолт паритетен общему
# (30000). Legacy `limits.summary_max_context_*` в Hybrid не читаются.

_WS_RE = re.compile(r"\s+")


@dataclasses.dataclass(frozen=True)
class FactPackageResult:
    """Fail-closed-результат сборки пакета (D4/D5).

    ``package`` — канонический ``FactPackage`` v1 (при ``not_built`` — None);
    ``reason`` — R17-safe код причины; ``metrics`` — аддитивные счётчики для
    S7/S8 (без узлов ExecutionGraph); ``budget`` — итоговый бюджет-срез.
    """

    status: str
    package: dict | None
    reason: str | None
    metrics: dict
    budget: dict

    @property
    def deliverable(self) -> bool:
        """Пакет допустим к передаче в L2 (§95/§106): ok/truncated."""
        return self.status in DELIVERABLE_STATUSES and self.package is not None

    @property
    def usable(self) -> bool:
        """Алиас ``deliverable`` (единая семантика с ``L1Result.usable``)."""
        return self.deliverable


# ── Доступ к полям (dict | объект) ─────────────────────────────────────────

def _as_int(value):
    """Строгий int без bool-ловушки (``True`` — не message_id)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _field(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _timestamp_of(id_space, message_id):
    key = id_space.order.get(message_id)
    if key is None:
        return None
    try:
        return int(key[0])
    except (TypeError, ValueError):
        return 0


def _payload_item_map(payload_items) -> dict:
    """``TG message_id → элемент §92`` (первое вхождение). Не выдумывается.

    ASAP-2 контракт (h): фрагменты пакета v2 несут ПОЛНЫЙ авторский контекст
    (author_id/display_name/timestamp/reply_to_id/text) — рассказчик
    понимает «кто что сказал / кто кому отвечал» (§12). Внутренняя техническая
    metadata (chat_id/DB id/message_type/mentions) в фрагмент НЕ попадает.
    """
    items: dict = {}
    for item in payload_items or []:
        if not isinstance(item, dict):
            continue
        mid = _as_int(item.get("message_id"))
        if mid is None or mid in items:
            continue
        items[mid] = item
    return items


def _payload_text_map(payload_items) -> dict:
    """``TG message_id → text`` (§92, первое вхождение) — из item-карты."""
    return {mid: ("" if item.get("text") is None else str(item.get("text")))
            for mid, item in _payload_item_map(payload_items).items()}


# ── Бюджет (ASAP-2 D7/контракт (g): hybrid-ключи) ──────────────────────────

def resolve_fact_package_budget(*, hot_get=None,
                                settings_obj=None) -> tuple[str, int]:
    """Бюджет пакета L2-входа — ТОЛЬКО ``limits.summary_hybrid_context_*``
    (единая точка ``resolve_hybrid_context_budget``) минус L2 output reserve
    и системный промпт (formula Q5; chars-режим симметрично). Legacy
    ``limits.summary_max_context_*`` НЕ читаются (§11:2353–2356). Per-chat-
    резолв — при врезке (генератор передаёт budget явным параметром)."""
    kind, limit = resolve_hybrid_context_budget(hot_get=hot_get,
                                                settings_obj=settings_obj)
    if limit <= 0:
        return kind, limit
    try:
        from services.summary_prompts import SUMMARY_L2_WRITER_SYSTEM_PROMPT
        system_text = SUMMARY_L2_WRITER_SYSTEM_PROMPT
    except Exception:  # pragma: no cover - защитная ветка
        system_text = ""
    effective = hybrid_input_budget(
        kind, limit, system_text=system_text,
        output_reserve=hybrid_output_reserve_tokens(
            kind="l2", settings_obj=settings_obj))
    return kind, effective


def _resolve_budget(budget):
    if isinstance(budget, (tuple, list)) and len(budget) == 2:
        kind = str(budget[0] or "tokens")
        try:
            limit = int(budget[1])
        except (TypeError, ValueError):
            limit = 0
        return kind, limit
    if isinstance(budget, int) and not isinstance(budget, bool):
        return "tokens", budget
    return resolve_fact_package_budget()


# ── Композиция полей темы ──────────────────────────────────────────────────

def _description(facts) -> tuple[str, bool]:
    """``description`` = дедуп-агрегация ``facts[].text`` (0 LLM, §4.2)."""
    seen: set = set()
    parts: list = []
    for fact in facts:
        text = _WS_RE.sub(" ", str(fact.get("text") or "").strip())
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        parts.append(text)
    description = DESCRIPTION_SEPARATOR.join(parts)
    if len(description) <= DESCRIPTION_MAX:
        return description, False
    cut = description[:DESCRIPTION_MAX]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ·"), True


def _select_fragments(message_ids, evidence_ids, item_map, id_space,
                      stats) -> list:
    """§4.5 + контракт (h): evidence-first отбор фрагментов из §92.

    Фрагмент v2 = ``{message_id, author_id, display_name, timestamp,
    reply_to_id, text}`` (text verbatim; ``reply_to_id`` — null без ответа).
    Пустой text в fragments не попадает (остаётся в хронологии).
    """
    ordered: list = []
    seen: set = set()
    for mid in sorted(evidence_ids, key=id_space.sort_key):
        if mid not in seen:
            seen.add(mid)
            ordered.append(mid)
    for mid in sorted(message_ids, key=id_space.sort_key):
        if mid not in seen:
            seen.add(mid)
            ordered.append(mid)
    fragments: list = []
    for mid in ordered:
        item = item_map.get(mid)
        if item is None:
            continue
        raw_text = item.get("text")
        text = "" if raw_text is None else str(raw_text)
        if not text:
            continue  # пустой text в fragments не попадает (остаётся в хронологии)
        if len(text) > FRAGMENT_MAX_CHARS:
            text = text[:FRAGMENT_MAX_CHARS]
            stats["fragment_char_truncated_count"] += 1
        reply_to = item.get("reply_to_id")
        fragments.append({
            "message_id": mid,
            "author_id": item.get("author_id"),
            "display_name": item.get("display_name"),
            "timestamp": _timestamp_of(id_space, mid),
            "reply_to_id": reply_to,
            "text": text,
        })
    return fragments


def _build_thread(thread, id_space, item_map, stats, topic_map=None):
    """Собрать ``PackageThread`` из канонического §95-треда.

    ``topic_map``: ``TG id → [thread_id…]`` (many-to-many карта контракта (h))
    — в хронологии каждого сообщения перечисляются ВСЕ темы, его содержащие
    (детерминированно из L1-выхода). Возвращает ``(thread|None, ids, reason)``.
    """
    if not isinstance(thread, dict):
        return None, [], REASON_BAD_INPUT

    thread_id = thread.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id:
        return None, [], REASON_BAD_INPUT

    raw_name = thread.get("topic", thread.get("name"))
    if not isinstance(raw_name, str) or not raw_name:
        return None, [], REASON_BAD_INPUT

    raw_ids = thread.get("message_ids")
    if not isinstance(raw_ids, list):
        return None, [], REASON_BAD_INPUT
    message_ids: list = []
    for mid in raw_ids:
        value = _as_int(mid)
        if value is None:
            return None, [], REASON_BAD_INPUT
        if value not in message_ids:
            message_ids.append(value)
    for mid in message_ids:
        if mid not in id_space.order:
            return None, [], REASON_MISSING_SOURCE

    raw_facts = thread.get("facts")
    if not isinstance(raw_facts, list):
        return None, [], REASON_BAD_INPUT
    facts: list = []
    for fact in raw_facts:
        if not isinstance(fact, dict):
            return None, [], REASON_BAD_INPUT
        text = fact.get("text")
        evidence = fact.get("evidence_message_ids")
        if not isinstance(text, str) or not isinstance(evidence, list):
            return None, [], REASON_BAD_INPUT
        evidence_ids: list = []
        for eid in evidence:
            value = _as_int(eid)
            if value is None:
                return None, [], REASON_BAD_INPUT
            if value not in message_ids:
                # defense-in-depth: repair (контракт (b) шаг 2) обязан было
                # расширить membership; если id всё же вне — это missing
                # источник (в.payload уже прошёл валидатор v2).
                return None, [], REASON_EVIDENCE_NOT_IN_THREAD
            if value not in evidence_ids:
                evidence_ids.append(value)
        facts.append({"text": text, "evidence_message_ids": evidence_ids})

    chronology: list = []
    for mid in sorted(message_ids, key=id_space.sort_key):
        timestamp = _timestamp_of(id_space, mid)
        if timestamp is None:
            return None, [], REASON_MISSING_SOURCE
        entry = {"message_id": mid, "timestamp": timestamp}
        if topic_map is not None:
            entry["topic_ids"] = list(topic_map.get(mid, [thread_id]))
        chronology.append(entry)

    evidence_union: set = set()
    for fact in facts:
        evidence_union.update(fact["evidence_message_ids"])
    evidence_ids = sorted(evidence_union, key=id_space.sort_key)

    fragments = _select_fragments(message_ids, evidence_ids, item_map,
                                  id_space, stats)

    description, description_truncated = _description(facts)
    if description_truncated:
        stats["description_truncated"] = True

    built = {
        "thread_id": thread_id,
        "name": raw_name,
        "description": description,
        "chronology": chronology,
        "facts": facts,
        "evidence_ids": evidence_ids,
        "fragments": fragments,
    }
    return built, message_ids, REASON_OK


def _apply_fragment_caps(threads) -> list:
    """Лимиты ``MAX_FRAGMENTS_PER_THREAD`` / ``MAX_FRAGMENTS_TOTAL`` (явно)."""
    skipped: list = []
    total = 0
    for thread in threads:
        kept: list = []
        for fragment in thread["fragments"]:
            if (len(kept) >= MAX_FRAGMENTS_PER_THREAD
                    or total >= MAX_FRAGMENTS_TOTAL):
                skipped.append(fragment["message_id"])
                continue
            kept.append(fragment)
            total += 1
        thread["fragments"] = kept
    return skipped


def _estimate(threads, unassigned, kind) -> int:
    content = {"threads": threads, "unassigned_message_ids": unassigned}
    text = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    return count_tokens(text) if kind == "tokens" else len(text)


def _enforce_budget(threads, unassigned, kind, limit):
    """Усечение под бюджет (D2): fragments → description → целые темы.

    Возвращает ``(skipped_ids, skipped_threads, descriptions_cleared, cut)``.
    Фрагменты вытесняются от старых, последние сохраняются (§93).
    """
    skipped_ids: list = []
    skipped_threads: list = []
    descriptions_cleared = 0
    if not limit or limit <= 0:
        return skipped_ids, skipped_threads, descriptions_cleared, False
    if _estimate(threads, unassigned, kind) <= limit:
        return skipped_ids, skipped_threads, descriptions_cleared, False
    cut = True

    # 1. Фрагменты: самый старый (по timestamp, message_id) — первым.
    while _estimate(threads, unassigned, kind) > limit:
        best_key = None
        best_index = None
        best_offset = None
        for index, thread in enumerate(threads):
            for offset, fragment in enumerate(thread["fragments"]):
                key = (fragment["timestamp"] or 0, fragment["message_id"])
                if best_key is None or key < best_key:
                    best_key = key
                    best_index = index
                    best_offset = offset
        if best_index is None:
            break
        removed = threads[best_index]["fragments"].pop(best_offset)
        skipped_ids.append(removed["message_id"])

    # 2. description → "" (производное поле), старая тема первой.
    if _estimate(threads, unassigned, kind) > limit:
        for thread in threads:
            if _estimate(threads, unassigned, kind) <= limit:
                break
            if thread["description"]:
                thread["description"] = ""
                descriptions_cleared += 1

    # 3. Целые темы — самая старая первой (факты/evidence не режутся частично).
    while _estimate(threads, unassigned, kind) > limit and threads:
        removed = threads.pop(0)
        skipped_threads.append(removed["thread_id"])

    return skipped_ids, skipped_threads, descriptions_cleared, cut


# ── Сборка пакета ──────────────────────────────────────────────────────────

def _service_section(l1_result, payload) -> dict:
    response_mode = str(_field(l1_result, "response_mode", "") or "")
    cover_prompt = str(_field(l1_result, "cover_prompt", "") or "")
    if isinstance(payload, dict):
        if not response_mode and isinstance(payload.get("response_mode"), str):
            response_mode = payload.get("response_mode")
        if not cover_prompt and isinstance(payload.get("cover_prompt"), str):
            cover_prompt = payload.get("cover_prompt")
    return {"response_mode": response_mode, "cover_prompt": cover_prompt}


def _base_package(status, service, budget, threads, unassigned) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "threads": threads,
        "unassigned_message_ids": unassigned,
        "service": service,
        "budget": budget,
    }


def _metrics(status, reason, *, l1_status, threads=(),
             description_truncated=False, skipped_ids=(), skipped_threads=(),
             descriptions_cleared=0, budget=None, l1_result=None,
             duration_ms=0.0, fragment_char_truncated=0) -> dict:
    budget = budget or {}
    messages = {entry["message_id"] for t in threads
                for entry in t.get("chronology") or []
                if isinstance(entry, dict)
                and entry.get("message_id") is not None}
    return {
        "status": status,
        "reason": reason or REASON_OK,
        "l1_status": l1_status,
        "threads_count": len(threads),
        # §18 (контракт (k)): FACT_PACKAGE topics= (дубль threads на переходный
        # период) и messages= (уникальные id в тредах).
        "topics_count": len(threads),
        "messages_count": len(messages),
        "facts_count": sum(len(t["facts"]) for t in threads),
        "fragments_count": sum(len(t["fragments"]) for t in threads),
        "evidence_count": sum(len(t["evidence_ids"]) for t in threads),
        "truncated_count": (len(skipped_ids) + len(skipped_threads)
                            + descriptions_cleared),
        "skipped_fragments_count": len(skipped_ids),
        "skipped_threads_count": len(skipped_threads),
        "descriptions_cleared_count": descriptions_cleared,
        "description_truncated": bool(description_truncated),
        "fragment_char_truncated_count": fragment_char_truncated,
        "kind": budget.get("kind"),
        "limit": budget.get("limit"),
        "estimated": budget.get("estimated"),
        "fits": budget.get("fits"),
        "l1_skipped_count": len(_field(l1_result, "skipped_ids", ()) or ()),
        "l1_chunk_count": _field(l1_result, "chunk_count", 0) or 0,
        "duration_ms": duration_ms,
    }


def _fail_result(status, reason, l1_result, kind, limit, duration_ms, *,
                 l1_status=None):
    service = _service_section(l1_result, None)
    budget = {"kind": kind, "limit": limit, "estimated": 0, "fits": True}
    # `not_built` — пакет НЕ строится (§9/D5); empty/invalid/error — объект с
    # threads=[] (структурный fail-closed, в L2 не передаётся).
    package = None if status == STATUS_NOT_BUILT else _base_package(
        status, service, budget, [], [])
    metrics = _metrics(status, reason, l1_status=l1_status or status,
                       budget=budget, l1_result=l1_result,
                       duration_ms=duration_ms)
    return FactPackageResult(status=status, package=package, reason=reason,
                             metrics=metrics, budget=budget)


def _build_from_payload(l1_result, payload, payload_items, kind, limit,
                        duration_ms):
    id_space = build_id_space(payload_items)
    item_map = _payload_item_map(payload_items)
    stats = {"description_truncated": False,
             "fragment_char_truncated_count": 0}

    raw_threads = payload.get("threads")
    if not isinstance(raw_threads, list):
        return _fail_result(STATUS_INVALID, REASON_BAD_INPUT, l1_result,
                            kind, limit, duration_ms, l1_status=STATUS_OK)

    # many-to-many карта topic_ids (контракт (h)): TG id → [thread_id…] —
    # ВСЕ темы, содержащие сообщение; порядок тем = порядок payload (детерм.).
    topic_map: dict = {}
    for raw_thread in raw_threads:
        if not isinstance(raw_thread, dict):
            continue
        tid = raw_thread.get("thread_id")
        if not isinstance(tid, str) or not tid:
            continue
        for mid in raw_thread.get("message_ids") or []:
            value = _as_int(mid)
            if value is None:
                continue
            bucket = topic_map.setdefault(value, [])
            if tid not in bucket:
                bucket.append(tid)

    threads: list = []
    in_threads: set = set()
    # ASAP-2 v2: пересечение membership между темами — НОРМА (many-to-many);
    # прежний fail-closed `message_in_multiple_threads` УДАЛЁН (контракт (h)).
    for raw_thread in raw_threads:
        thread, message_ids, reason = _build_thread(raw_thread, id_space,
                                                    item_map, stats,
                                                    topic_map=topic_map)
        if thread is None:
            return _fail_result(STATUS_INVALID, reason, l1_result, kind,
                                limit, duration_ms, l1_status=STATUS_OK)
        in_threads.update(message_ids)
        threads.append(thread)

    raw_unassigned = payload.get("unassigned_message_ids", [])
    if not isinstance(raw_unassigned, list):
        return _fail_result(STATUS_INVALID, REASON_BAD_INPUT, l1_result, kind,
                            limit, duration_ms, l1_status=STATUS_OK)
    unassigned: list = []
    for mid in raw_unassigned:
        value = _as_int(mid)
        if value is None:
            return _fail_result(STATUS_INVALID, REASON_BAD_INPUT, l1_result,
                                kind, limit, duration_ms, l1_status=STATUS_OK)
        if value not in id_space.order:
            return _fail_result(STATUS_INVALID, REASON_MISSING_SOURCE,
                                l1_result, kind, limit, duration_ms,
                                l1_status=STATUS_OK)
        if value in in_threads:
            # defense-in-depth: конфликт разрешает repair (membership
            # побеждает, контракт (b) шаг 5); до пакета доходить не должен.
            return _fail_result(STATUS_INVALID, REASON_UNASSIGNED_CONFLICT,
                                l1_result, kind, limit, duration_ms,
                                l1_status=STATUS_OK)
        if value not in unassigned:
            unassigned.append(value)
    unassigned = sorted(unassigned, key=id_space.sort_key)

    # ASC тем по первой паре хронологии (стабильно, детерминированно).
    threads.sort(key=lambda t: id_space.sort_key(t["chronology"][0]["message_id"])
                 if t["chronology"] else (0, 0))

    # Лимиты фрагментов (явные, «не резать молча»).
    skipped_ids = _apply_fragment_caps(threads)

    # Бюджет L2-входа (D2).
    budget_skipped, skipped_threads, descriptions_cleared, _cut = \
        _enforce_budget(threads, unassigned, kind, limit)
    skipped_ids.extend(budget_skipped)

    estimated = _estimate(threads, unassigned, kind)
    budget = {"kind": kind, "limit": limit, "estimated": estimated,
              "fits": bool(not limit or limit <= 0 or estimated <= limit)}

    input_truncated = bool(_field(l1_result, "truncated", False)) \
        or str(_field(l1_result, "status", "")) == STATUS_TRUNCATED
    truncated = bool(skipped_ids or skipped_threads or descriptions_cleared
                     or input_truncated)

    if not threads:
        status = STATUS_EMPTY
        reason = REASON_BUDGET_EMPTY if (skipped_ids or skipped_threads) \
            else REASON_EMPTY
    elif truncated:
        status = STATUS_TRUNCATED
        reason = REASON_OK
    else:
        status = STATUS_OK
        reason = REASON_OK

    service = _service_section(l1_result, payload)
    package = _base_package(status, service, budget, threads, unassigned)
    metrics = _metrics(
        status, reason, l1_status=str(_field(l1_result, "status", "") or ""),
        threads=threads, description_truncated=stats["description_truncated"],
        skipped_ids=skipped_ids, skipped_threads=skipped_threads,
        descriptions_cleared=descriptions_cleared, budget=budget,
        l1_result=l1_result, duration_ms=duration_ms,
        fragment_char_truncated=stats["fragment_char_truncated_count"])
    metrics["skipped_ids"] = tuple(skipped_ids)
    metrics["skipped_threads"] = tuple(skipped_threads)
    return FactPackageResult(status=status, package=package, reason=reason,
                             metrics=metrics, budget=budget)


# ── Публичный интерфейс (объявлен для S5, не вызывается в живом пути) ─────

def build_fact_package(l1_result, payload_items, *, budget=None,
                       correlation_id=None) -> FactPackageResult:
    """Собрать ``FactPackage`` v2 из ``L1Result`` + §92-payload (D1/D5).

    ``budget`` — ``(kind, limit)``; ``None`` → hybrid-ключи
    ``limits.summary_hybrid_context_*`` (контракт (g)). 0 LLM-вызовов, вход не
    мутируется; любое исключение → fail-closed ``error``/``internal_error``
    (в L2 не передаётся). ``correlation_id`` — аддитивный R17-safe параметр
    логирования (§109; формальный ``run_id`` вводит S7).
    """
    started = time.perf_counter()
    kind, limit = _resolve_budget(budget)
    l1_status = str(_field(l1_result, "status", "") or "none")
    _log_start(correlation_id=correlation_id, l1_status=l1_status, kind=kind,
               limit=limit)
    try:
        result = _dispatch(l1_result, payload_items, kind, limit,
                           correlation_id, started)
    except Exception:
        duration = (time.perf_counter() - started) * 1000.0
        logger.warning(
            "FACT_PACKAGE_ERROR | run_id=%s | reason=%s | duration_ms=%.0f",
            correlation_id or "none", REASON_INTERNAL_ERROR, duration)
        result = _fail_result(STATUS_ERROR, REASON_INTERNAL_ERROR, l1_result,
                              kind, limit, duration, l1_status=l1_status)
    _log_complete(correlation_id=correlation_id, result=result)
    return result


def _dispatch(l1_result, payload_items, kind, limit, correlation_id, started):
    if l1_result is None:
        duration = (time.perf_counter() - started) * 1000.0
        return _fail_result(STATUS_NOT_BUILT, REASON_NO_RESULT, l1_result,
                            kind, limit, duration, l1_status="none")

    status = _field(l1_result, "status")
    if status not in _KNOWN_L1_STATUSES:
        duration = (time.perf_counter() - started) * 1000.0
        return _fail_result(STATUS_NOT_BUILT, REASON_UNKNOWN_STATUS, l1_result,
                            kind, limit, duration,
                            l1_status=str(status or "none"))

    payload = _field(l1_result, "payload")
    if status in (STATUS_OK, STATUS_TRUNCATED):
        if not isinstance(payload, dict):
            duration = (time.perf_counter() - started) * 1000.0
            return _fail_result(STATUS_NOT_BUILT, REASON_PAYLOAD_MISSING,
                                l1_result, kind, limit, duration,
                                l1_status=status)
        duration = (time.perf_counter() - started) * 1000.0
        return _build_from_payload(l1_result, payload, payload_items, kind,
                                   limit, duration)

    # empty / invalid / error — fail-closed: threads=[], в L2 не передаётся.
    duration = (time.perf_counter() - started) * 1000.0
    reason = _field(l1_result, "invalid_reason") \
        if status in (STATUS_INVALID, STATUS_ERROR) else REASON_EMPTY
    if status in (STATUS_INVALID, STATUS_ERROR):
        _log_error(correlation_id=correlation_id, reason=reason,
                   duration_ms=duration)
    return _fail_result(status, reason, l1_result, kind, limit, duration,
                        l1_status=status)


# ── LEVEL-2: deterministic fallback-пакет (ASAP-2 §8/контракт (i), D4) ─────

def build_fallback_package(payload_items, *, budget=None,
                           correlation_id=None, chat_id=None,
                           reason: str = "l1_unusable"):
    """Пакет «Общий ход обсуждения» (0 LLM) для LEVEL-2, когда L1 непригоден
    ЛЮБАЯ причина (invalid после correction, error/timeout, useless,
    too_many_*, empty).

    §8:2243–2260: одна тема ``thread_001`` с ``name="Общий ход обсуждения"``;
    ``description=""``, ``facts=[]``;
    ``chronology`` = ВСЕ filtered source-сообщения (§92, после S1/S2) ASC c
    ``topic_ids=["thread_001"]``; ``fragments`` = все сообщения с полями v2
    (author + text + reply links, контракт (h)) и существующими капами/бюджетом
    (fragments→description→темы, «старые первыми»). Статус ``ok``/``truncated``
    — обязан проходить deliverability-гейт ``run_l2`` → L2 вызывается в любом
    случае (§8:2260). Пустой payload (0 сообщений) → ``None``: пакет не
    строится — НЕ failure, существующая empty-семантика (матрица строка 2).
    """
    items = [item for item in (payload_items or []) if isinstance(item, dict)]
    if not items:
        return None
    started = time.perf_counter()
    kind, limit = _resolve_budget(budget)
    id_space = build_id_space(items)
    item_map = _payload_item_map(items)
    ordered_ids = sorted(id_space.ids, key=id_space.sort_key)
    stats = {"fragment_char_truncated_count": 0}
    # Фрагменты = ВСЕ сообщения (хронология = тот же порядок ASC).
    fragments = _select_fragments(ordered_ids, [], item_map, id_space, stats)
    thread = {
        "thread_id": FALLBACK_THREAD_ID,
        "name": FALLBACK_TOPIC_NAME,
        "description": "",
        "chronology": [
            {"message_id": mid, "timestamp": _timestamp_of(id_space, mid),
             "topic_ids": [FALLBACK_THREAD_ID]}
            for mid in ordered_ids
        ],
        "facts": [],
        "evidence_ids": [],
        "fragments": fragments,
    }
    threads = [thread]
    skipped_ids = _apply_fragment_caps(threads)
    budget_skipped, skipped_threads, _cleared, _cut = _enforce_budget(
        threads, [], kind, limit)
    skipped_ids.extend(budget_skipped)
    estimated = _estimate(threads, [], kind)
    budget_dict = {"kind": kind, "limit": limit, "estimated": estimated,
                   "fits": bool(not limit or limit <= 0
                                or estimated <= limit)}
    truncated = bool(skipped_ids or skipped_threads)
    status = STATUS_TRUNCATED if truncated else STATUS_OK
    service = {"response_mode": "", "cover_prompt": ""}
    package = _base_package(status, service, budget_dict, threads, [])
    metrics = _metrics(status, REASON_OK, l1_status="fallback",
                       threads=threads, skipped_ids=skipped_ids,
                       skipped_threads=skipped_threads, budget=budget_dict,
                       l1_result=None,
                       duration_ms=(time.perf_counter() - started) * 1000.0,
                       fragment_char_truncated=stats[
                           "fragment_char_truncated_count"])
    # §18 (контракт (k)): L1_FALLBACK_PACKAGE — WARN с причиной отказа L1 и
    # размерами пакета (только числа/коды, R17-safe).
    metrics["fallback_reason"] = str(reason or "l1_unusable")
    logger.warning(
        "L1_FALLBACK_PACKAGE | run_id=%s | chat_id=%s | reason=%s | "
        "fragments=%d | chronology=%d",
        correlation_id or "none", chat_id if chat_id is not None else "-",
        metrics["fallback_reason"],
        metrics.get("fragments_count", 0),
        metrics.get("messages_count", 0))
    return FactPackageResult(status=status, package=package, reason=REASON_OK,
                             metrics=metrics, budget=budget_dict)


# ── §109: логи (аддитивные, R17-safe) ──────────────────────────────────────

def _log_start(*, correlation_id, l1_status, kind, limit):
    logger.info(
        "FACT_PACKAGE_START | run_id=%s | l1_status=%s | kind=%s | limit=%d",
        correlation_id or "none", l1_status, kind, limit)


def _log_complete(*, correlation_id, result: FactPackageResult):
    metrics = result.metrics or {}
    # §18 (контракт (k)): аддитивно topics= (дубль threads на переходный
    # период) и messages= (уникальные id в тредах).
    logger.info(
        "FACT_PACKAGE_COMPLETE | run_id=%s | status=%s | reason=%s | "
        "threads=%d | topics=%d | messages=%d | facts=%d | fragments=%d | "
        "evidence=%d | "
        "skipped_fragments=%d | skipped_threads=%d | descriptions_cleared=%d | "
        "estimated=%s | limit=%s | fits=%s | duration_ms=%.0f",
        correlation_id or "none", result.status, result.reason or REASON_OK,
        metrics.get("threads_count", 0), metrics.get("topics_count", 0),
        metrics.get("messages_count", 0),
        metrics.get("facts_count", 0),
        metrics.get("fragments_count", 0), metrics.get("evidence_count", 0),
        metrics.get("skipped_fragments_count", 0),
        metrics.get("skipped_threads_count", 0),
        metrics.get("descriptions_cleared_count", 0),
        metrics.get("estimated", 0), metrics.get("limit", 0),
        metrics.get("fits", True), metrics.get("duration_ms", 0.0))
    if result.status == STATUS_TRUNCATED or result.metrics.get("truncated_count"):
        # §93/§96: «не резать молча» — усечение видно WARN-логом (R17: числа/id).
        logger.warning(
            "FACT_PACKAGE_TRUNCATED | run_id=%s | status=%s | "
            "skipped_fragments=%d | skipped_threads=%d | "
            "descriptions_cleared=%d | limit=%s | estimated=%s",
            correlation_id or "none", result.status,
            metrics.get("skipped_fragments_count", 0),
            metrics.get("skipped_threads_count", 0),
            metrics.get("descriptions_cleared_count", 0),
            metrics.get("limit", 0), metrics.get("estimated", 0))


def _log_error(*, correlation_id, reason, duration_ms):
    logger.warning(
        "FACT_PACKAGE_ERROR | run_id=%s | reason=%s | duration_ms=%.0f",
        correlation_id or "none", reason or REASON_INTERNAL_ERROR, duration_ms)


# ── Сериализация (детерминизм/байт-идентичность) ───────────────────────────

def serialize_package(package) -> str:
    """Канонический JSON пакета (фиксированный порядок ключей/разделители)."""
    return json.dumps(package, ensure_ascii=False, separators=(",", ":"))
