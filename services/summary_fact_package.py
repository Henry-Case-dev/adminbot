"""S4 round1026 (ADR-1026-6 D1–D6) — «Пакет фактов §96» (вход L2).

**Чистый** модуль (0 LLM-вызовов, без БД/сети/системных часов бизнес-логики):
из валидированного ``L1Result`` (§95, S3) и §92-payload
(``summary_context_restore.build_l1_payload``) детерминированно собирает
пакет фактов для L2 (§96): на каждую тему — название, описание, хронологию,
факты, подтверждающие ID и необходимые исходные фрагменты текста. Весь сырой
лог повторно НЕ передаётся; «доказательства» не генерируются.

Контракт пакета ``FactPackage`` v1 (D1):
  * топ-уровень ровно: ``{schema_version, status, threads[],
    unassigned_message_ids[], service{response_mode, cover_prompt},
    budget{kind, limit, estimated, fits}}``;
  * тема ровно: ``{thread_id, name, description, chronology[], facts[],
    evidence_ids[], fragments[]}``;
  * ``name`` = ``topic`` verbatim; ``description`` = детерминированная
    агрегация ``facts[].text`` (дедуп/схлопывание пробелов/кап
    ``DESCRIPTION_MAX``; нет фактов → ``""``) — **не LLM/проза**;
  * ``chronology`` = ASC ``(timestamp, message_id)`` из §92-payload;
  * ``facts`` / ``evidence_ids`` — verbatim-факты L1 + union evidence (ASC);
  * ``fragments`` = §92-текст, приоритет evidence-first + лимиты;
  * ``service`` — транзит служебных полей (D3), вне L2-контента;
  * фиксированный порядок ключей; двойной прогон байт-идентичен.

Бюджет L2-входа (D2) — переиспользование существующих
``limits.summary_max_context_tokens``/``_chars`` через ``resolve_chat_limit``
(Δ каталога = 0, новых env нет). Усечение: фрагменты (старые первыми,
последние сохраняются, §93) → ``description`` → целые темы; факты/evidence
не режутся частично; любое вытеснение → ``truncated`` + ``skipped_ids``/WARN.

Fail-closed (D5): ``ok`` → ``ok``; ``truncated`` → ``truncated`` + проброс;
``empty``/``invalid``/``error`` → ``threads=[]`` и в L2 НЕ передаётся
(§95/§106); нет ``usable``/``payload`` → ``not_built`` (пакет не строится).
ID — TG ``message_id`` (§92/§95); DB ``id`` в публичное поле пакета не
попадает. Висячие/фабрикованные ссылки → ``invalid``. Вход не мутируется.
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
from services.token_counter import count_tokens, resolve_chat_limit

logger = logging.getLogger(__name__)

MODULE = "summary"
STEP = "fact_package"

# ── Схема пакета v1 ────────────────────────────────────────────────────────

SCHEMA_VERSION = 1

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
REASON_OK = "ok"
REASON_EMPTY = "empty"
REASON_NO_RESULT = "no_result"
REASON_UNKNOWN_STATUS = "unknown_status"
REASON_PAYLOAD_MISSING = "payload_missing"
REASON_BAD_INPUT = "bad_type"
REASON_MISSING_SOURCE = "missing_source"
REASON_UNKNOWN_MESSAGE_ID = "unknown_message_id"
REASON_EVIDENCE_NOT_IN_THREAD = "evidence_not_in_thread"
REASON_MESSAGE_IN_MULTIPLE_THREADS = "message_in_multiple_threads"
REASON_UNASSIGNED_CONFLICT = "unassigned_conflict"
REASON_BUDGET_EMPTY = "budget_empty"
REASON_INTERNAL_ERROR = "internal_error"

# ── Лимиты композиции (константы модуля, Δ каталога = 0) ───────────────────

DESCRIPTION_MAX = 500
DESCRIPTION_SEPARATOR = " · "
FRAGMENT_MAX_CHARS = 1000
MAX_FRAGMENTS_PER_THREAD = 30
MAX_FRAGMENTS_TOTAL = 500

# §5.6: бюджет — существующие ключи (`limits.summary_max_context_*`); дефолт
# токенов паритетен `_SUMMARY_CONTEXT_TOKEN_DEFAULT` (30000).
TOKEN_DEFAULT = 30000
CHARS_ENV = "SUMMARY_MAX_CONTEXT_CHARS"

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


def _payload_text_map(payload_items) -> dict:
    """``TG message_id → text`` (§92, первое вхождение). Не выдумывается."""
    texts: dict = {}
    for item in payload_items or []:
        if not isinstance(item, dict):
            continue
        mid = _as_int(item.get("message_id"))
        if mid is None or mid in texts:
            continue
        value = item.get("text")
        texts[mid] = "" if value is None else str(value)
    return texts


# ── Бюджет (D2) ────────────────────────────────────────────────────────────

def resolve_fact_package_budget(*, hot_get=None,
                                settings_obj=None) -> tuple[str, int]:
    """Бюджет пакета L2-входа из ``limits.summary_max_context_*`` (D2).

    Токенный приоритет + аварийный chars-fallback — штатная семантика
    ``resolve_chat_limit``; новых env/каталога нет (Δ каталога = 0).
    Per-chat-резолв — S5 (при врезке).
    """
    if hot_get is None:
        from services import hot_config as hot
        hot_get = hot.get
    st = settings_obj or settings
    token_value = hot_get("limits.summary_max_context_tokens",
                          getattr(st, "SUMMARY_MAX_CONTEXT_TOKENS", None))
    chars_value = hot_get("limits.summary_max_context_chars",
                          getattr(st, "SUMMARY_MAX_CONTEXT_CHARS", 120000))
    return resolve_chat_limit(token_value, TOKEN_DEFAULT, CHARS_ENV,
                              int(chars_value or 0), "SUMMARY_FACT_PACKAGE")


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


def _select_fragments(message_ids, evidence_ids, text_map, id_space,
                      stats) -> list:
    """§4.5: evidence-first отбор фрагментов из §92 (текст verbatim)."""
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
        text = text_map.get(mid, "")
        if not text:
            continue  # пустой text в fragments не попадает (остаётся в хронологии)
        if len(text) > FRAGMENT_MAX_CHARS:
            text = text[:FRAGMENT_MAX_CHARS]
            stats["fragment_char_truncated_count"] += 1
        fragments.append({"message_id": mid,
                          "timestamp": _timestamp_of(id_space, mid),
                          "text": text})
    return fragments


def _build_thread(thread, id_space, text_map, stats):
    """Собрать ``PackageThread`` из канонического §95-треда.

    Возвращает ``(thread | None, message_ids, reason)``.
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
                return None, [], REASON_EVIDENCE_NOT_IN_THREAD
            if value not in evidence_ids:
                evidence_ids.append(value)
        facts.append({"text": text, "evidence_message_ids": evidence_ids})

    chronology: list = []
    for mid in sorted(message_ids, key=id_space.sort_key):
        timestamp = _timestamp_of(id_space, mid)
        if timestamp is None:
            return None, [], REASON_MISSING_SOURCE
        chronology.append({"message_id": mid, "timestamp": timestamp})

    evidence_union: set = set()
    for fact in facts:
        evidence_union.update(fact["evidence_message_ids"])
    evidence_ids = sorted(evidence_union, key=id_space.sort_key)

    fragments = _select_fragments(message_ids, evidence_ids, text_map,
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
    return {
        "status": status,
        "reason": reason or REASON_OK,
        "l1_status": l1_status,
        "threads_count": len(threads),
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
    text_map = _payload_text_map(payload_items)
    stats = {"description_truncated": False,
             "fragment_char_truncated_count": 0}

    raw_threads = payload.get("threads")
    if not isinstance(raw_threads, list):
        return _fail_result(STATUS_INVALID, REASON_BAD_INPUT, l1_result,
                            kind, limit, duration_ms, l1_status=STATUS_OK)

    threads: list = []
    seen: set = set()
    for raw_thread in raw_threads:
        thread, message_ids, reason = _build_thread(raw_thread, id_space,
                                                    text_map, stats)
        if thread is None:
            return _fail_result(STATUS_INVALID, reason, l1_result, kind,
                                limit, duration_ms, l1_status=STATUS_OK)
        for mid in message_ids:
            if mid in seen:
                return _fail_result(STATUS_INVALID,
                                    REASON_MESSAGE_IN_MULTIPLE_THREADS,
                                    l1_result, kind, limit, duration_ms,
                                    l1_status=STATUS_OK)
            seen.add(mid)
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
        if value in seen:
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
    """Собрать ``FactPackage`` v1 из ``L1Result`` + §92-payload (D1/D5).

    ``budget`` — ``(kind, limit)``; ``None`` → существующие
    ``limits.summary_max_context_*`` (D2). 0 LLM-вызовов, вход не мутируется;
    любое исключение → fail-closed ``error``/``internal_error`` (в L2 не
    передаётся). ``correlation_id`` — аддитивный R17-safe параметр логирования
    (§109; формальный ``run_id`` вводит S7).
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


# ── §109: логи (аддитивные, R17-safe) ──────────────────────────────────────

def _log_start(*, correlation_id, l1_status, kind, limit):
    logger.info(
        "FACT_PACKAGE_START | run_id=%s | l1_status=%s | kind=%s | limit=%d",
        correlation_id or "none", l1_status, kind, limit)


def _log_complete(*, correlation_id, result: FactPackageResult):
    metrics = result.metrics or {}
    logger.info(
        "FACT_PACKAGE_COMPLETE | run_id=%s | status=%s | reason=%s | "
        "threads=%d | facts=%d | fragments=%d | evidence=%d | "
        "skipped_fragments=%d | skipped_threads=%d | descriptions_cleared=%d | "
        "estimated=%s | limit=%s | fits=%s | duration_ms=%.0f",
        correlation_id or "none", result.status, result.reason or REASON_OK,
        metrics.get("threads_count", 0), metrics.get("facts_count", 0),
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
