"""S3 round1026 (ADR-1026-5 D5/D2) — контракт L1 «Кластеризатор» (§94–§95).

**Чистый** модуль (0 LLM-вызовов, без БД/сети/системных часов): единый
источник строгой JSON-схемы §95 для парсера, валидатора, канонизатора и
тестов; fail-closed-результат ``L1Result`` с кодом причины.

Контракт (спека §5.1/§5.2/§5.3, D2/D5):
  * ``{schema_version:1, threads:[{thread_id, topic, message_ids[],
    facts:[{text, evidence_message_ids[]}]}], unassigned_message_ids[]}`` +
    опциональные служебные ``response_mode``/``cover_prompt`` того же JSON;
  * **лишние поля → invalid** (top-level ровно 5 ключей, thread — 4, fact — 2);
  * лимиты: тредов ≤100, фактов/тред ≤30, всего фактов ≤1000, ``topic`` ≤200
    без ``\\n``, ``fact.text`` ≤500 без ``\\n\\n``, без системных тегов (R17)
    и markdown-заголовков; превышение → ``invalid`` (без тихого усечения);
  * **пространства ID явные:** вход/выход L1 — **TG** ``message_id`` (§92);
    ``Fragment.message_ids`` (DB ``id``) сюда НЕ попадают — конвертация через
    таблицу соответствия строк окна выполняется упаковщиком §93
    (``summary_l1_clusterizer``), и её провал → ``id_space_mismatch``;
  * ``evidence_message_ids`` ⊆ ``message_ids`` своего треда; один id ровно в
    одном треде; ``unassigned ∩ threads = ∅``; пропущенные моделью payload-id
    детерминированно добавляются в ``unassigned`` (``auto_unassigned_count``);
  * детерминизм: дедуп + ASC ``(timestamp, message_id)``, перенумерация
    ``thread_001…``, дедуп фактов по нормализованному тексту с объединением
    evidence; повторный прогон на том же входе — байт-идентичен.
"""
from __future__ import annotations

import dataclasses
import logging
import re

from services.system2_handoff import (
    contains_system_ids,
    normalize_cover_prompt,
    normalize_response_mode,
    parse_json_object,
)

logger = logging.getLogger(__name__)

# ── Схема §95 (единый источник для парсера/валидатора/тестов) ──────────────

SCHEMA_VERSION = 1
MAX_THREADS = 100
MAX_FACTS_PER_THREAD = 30
MAX_FACTS_TOTAL = 1000
TOPIC_MAX = 200
FACT_MAX = 500
THREAD_ID_MAX = 64
THREAD_ID_PATTERN = r"^[A-Za-z0-9_\-]{1,64}$"
THREAD_ID_RE = re.compile(THREAD_ID_PATTERN)
_HEADING_RE = re.compile(r"(?m)^#{1,6}\s")
_WS_RE = re.compile(r"\s+")

THREAD_ID_TEMPLATE = "thread_%03d"

TOP_LEVEL_FIELDS: frozenset[str] = frozenset(
    {"schema_version", "threads", "unassigned_message_ids",
     "response_mode", "cover_prompt"})
THREAD_FIELDS: frozenset[str] = frozenset(
    {"thread_id", "topic", "message_ids", "facts"})
FACT_FIELDS: frozenset[str] = frozenset({"text", "evidence_message_ids"})

# Статусы L1Result (D5). ok|empty|invalid|truncated|error; в L2 передаётся
# только ok/truncated (`usable`), пустое/невалидное/сбойное — fail-closed.
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_INVALID = "invalid"
STATUS_TRUNCATED = "truncated"
STATUS_ERROR = "error"
USABLE_STATUSES: frozenset[str] = frozenset({STATUS_OK, STATUS_TRUNCATED})

# Коды причин (R17-safe: только коды, без контента модели).
REASON_OK = "ok"
REASON_EMPTY_RESPONSE = "empty_response"
REASON_INVALID_JSON = "invalid_json"
REASON_UNKNOWN_FIELD = "unknown_field"
REASON_BAD_TYPE = "bad_type"
REASON_BAD_SCHEMA_VERSION = "bad_schema_version"
REASON_INVALID_THREAD_ID = "invalid_thread_id"
REASON_INVALID_TOPIC = "invalid_topic"
REASON_INVALID_FACT = "invalid_fact"
REASON_UNKNOWN_MESSAGE_ID = "unknown_message_id"
REASON_EVIDENCE_NOT_IN_THREAD = "evidence_not_in_thread"
REASON_MESSAGE_IN_MULTIPLE_THREADS = "message_in_multiple_threads"
REASON_UNASSIGNED_CONFLICT = "unassigned_conflict"
REASON_TOO_MANY_THREADS = "too_many_threads"
REASON_TOO_MANY_FACTS = "too_many_facts"
REASON_TOO_MANY_FACTS_TOTAL = "too_many_facts_total"
REASON_ID_SPACE_MISMATCH = "id_space_mismatch"
REASON_LLM_ERROR = "llm_error"
REASON_LLM_TIMEOUT = "llm_timeout"
REASON_INTERNAL_ERROR = "internal_error"

# Пространства ID (D5): явные имена — «на глаз» не конвертируем.
ID_SPACE_TG = "tg_message_id"   # payload §92 / выход L1
ID_SPACE_DB = "db_id"           # Fragment.message_ids (§93, упаковка)


# ── Пространство ID payload (§92) ──────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class IdSpace:
    """Индекс payload по **TG** ``message_id`` (первое вхождение).

    ``order``: ``tg_id → (timestamp, message_id)`` — детерминированный
    ASC-порядок §5.2/§5.3. Не-int id (None/строки) в пространство не попадают
    и моделью не адресуются (метаданные не выдумываются, §92).
    """

    order: dict

    @property
    def ids(self) -> frozenset:
        return frozenset(self.order)

    def contains(self, message_id) -> bool:
        return message_id in self.order

    def sort_key(self, message_id):
        key = self.order.get(message_id)
        if key is not None:
            return key
        # Неизвестный id сюда не доходит (сначала unknown_message_id), но
        # ключ обязан быть сравнимым — детерминированный хвост.
        try:
            return (0, int(message_id))
        except (TypeError, ValueError):
            return (0, 0)


def _as_int(value):
    """Строгий int без bool-ловушки (``True`` — не message_id)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def sort_key_from_item(item) -> tuple:
    """Ключ ASC ``(timestamp, message_id)`` элемента §92."""
    ts = item.get("timestamp") if isinstance(item, dict) else None
    try:
        ts_key = int(ts or 0)
    except (TypeError, ValueError):
        ts_key = 0
    mid = _as_int(item.get("message_id")) if isinstance(item, dict) else None
    return (ts_key, mid if mid is not None else 0)


def build_id_space(payload_items) -> IdSpace:
    """Индекс payload §92 по TG ``message_id`` (первое вхождение)."""
    order: dict = {}
    for item in payload_items or []:
        if not isinstance(item, dict):
            continue
        mid = _as_int(item.get("message_id"))
        if mid is None or mid in order:
            continue
        order[mid] = sort_key_from_item(item)
    return IdSpace(order=order)


# ── Результат L1 (fail-closed, D5) ─────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class L1Result:
    """Fail-closed-результат L1 (ок/пусто/невалидно/усечено/ошибка).

    ``payload`` — канонизированный §95-объект (только при ``ok``/``truncated``
    с ≥1 тредом); ``empty``/``invalid``/``error`` в L2 НЕ передаются (§95/§106).
    ``skipped_ids`` — DB ``id`` сообщений, вытесненных бюджетом §93 (упаковка,
    пространство S1/S2), ``skipped_tg_ids`` — те же сообщения в TG-пространстве;
    R17: только id/числа, без текстов.
    """

    status: str
    payload: dict | None
    invalid_reason: str | None
    threads_count: int
    facts_count: int
    auto_unassigned_count: int
    skipped_ids: tuple
    skipped_tg_ids: tuple
    response_mode: str
    cover_prompt: str
    duration_ms: float
    truncated: bool = False
    chunk_count: int = 0

    @property
    def usable(self) -> bool:
        """Результат допустим к передаче в L2 (§95/§106): ok/truncated."""
        return self.status in USABLE_STATUSES and self.payload is not None

    def as_metrics(self) -> dict:
        """Аддитивные счётчики для S7/S8 (без узлов ExecutionGraph)."""
        return {
            "status": self.status,
            "threads_count": self.threads_count,
            "facts_count": self.facts_count,
            "auto_unassigned_count": self.auto_unassigned_count,
            "invalid_reason": self.invalid_reason,
            "truncated": self.truncated,
            "skipped_count": len(self.skipped_ids),
            "chunk_count": self.chunk_count,
            "response_mode": self.response_mode,
            "duration_ms": self.duration_ms,
        }


def _make_result(status: str, *, payload=None, reason=None, threads=0, facts=0,
                 auto_unassigned=0, skipped_ids=(), skipped_tg_ids=(),
                 response_mode="", cover_prompt="", duration_ms=0.0,
                 truncated=False, chunk_count=0) -> L1Result:
    return L1Result(
        status=status, payload=payload, invalid_reason=reason,
        threads_count=threads, facts_count=facts,
        auto_unassigned_count=auto_unassigned,
        skipped_ids=tuple(skipped_ids or ()),
        skipped_tg_ids=tuple(skipped_tg_ids or ()),
        response_mode=response_mode, cover_prompt=cover_prompt,
        duration_ms=duration_ms, truncated=truncated, chunk_count=chunk_count)


def invalid_result(reason: str, **kwargs) -> L1Result:
    """Fail-closed ``invalid``: ``payload=None`` — в L2 нечего передавать."""
    return _make_result(STATUS_INVALID, reason=reason, **kwargs)


def error_result(reason: str, **kwargs) -> L1Result:
    """``error``: исключение/``LLMError`` — тихой потери нет (WARN L1_ERROR)."""
    return _make_result(STATUS_ERROR, reason=reason, **kwargs)


def empty_result(**kwargs) -> L1Result:
    """``empty``: валидная структура без тредов → в L2 не передаётся."""
    return _make_result(STATUS_EMPTY, **kwargs)


# ── Парсер (переиспользует политику system2_handoff) ───────────────────────

def parse_l1_response(raw: str) -> tuple[dict | None, str]:
    """Строгий разбор ответа L1: ``(data | None, reason)``.

    ``ok`` | ``empty_response`` (пустой ответ) | ``invalid_json`` (не JSON /
    не объект). Фенсы/обрамление/reasoning-теги снимает существующий
    ``system2_handoff.parse_json_object`` (политика не переписывается).
    """
    source = str(raw or "")
    if not source.strip():
        return None, REASON_EMPTY_RESPONSE
    data = parse_json_object(source)
    if not isinstance(data, dict):
        return None, REASON_INVALID_JSON
    return data, REASON_OK


# ── Нормализация служебных полей (D2) ──────────────────────────────────────

def service_fields(data: dict) -> tuple[str, str]:
    """``(response_mode, cover_prompt)`` — нормализаторы того же JSON (D2).

    Невалидное/отсутствующее → ``""`` (graceful-деградация как сегодня:
    резервный режим/фолбэк обложки решают существующие ключи/пути §104).
    """
    if not isinstance(data, dict):
        return "", ""
    return (normalize_response_mode(data.get("response_mode")),
            normalize_cover_prompt(data.get("cover_prompt")))


# ── Валидация + канонизация §95 ────────────────────────────────────────────

def _fact_key(text: str) -> str:
    """Ключ дедупа фактов: strip + casefold + схлопывание пробелов."""
    return _WS_RE.sub(" ", str(text or "").strip()).casefold()


def _valid_topic(topic):
    if not isinstance(topic, str):
        return None
    if "\n" in topic or "\r" in topic:
        return None
    value = topic.strip()
    if not value or len(value) > TOPIC_MAX:
        return None
    return value


def _valid_fact_text(text):
    if not isinstance(text, str):
        return None
    value = text.strip()
    if not value or len(value) > FACT_MAX:
        return None
    if "\n\n" in value:
        return None
    if contains_system_ids(value):
        return None
    if _HEADING_RE.search(value):
        return None
    return value


def validate_l1_response(data, id_space: IdSpace, *,
                         duration_ms: float = 0.0,
                         skipped_ids=(), skipped_tg_ids=(),
                         truncated: bool = False,
                         chunk_count: int = 0) -> L1Result:
    """Проверить и канонизировать §95-объект (fail-closed, детерминированно).

    Возвращает ``ok`` (≥1 тред; payload канонизирован), ``empty`` (валидная
    структура без тредов) либо ``invalid`` с кодом причины. Не бросает.
    """
    base = dict(duration_ms=duration_ms, skipped_ids=skipped_ids,
                skipped_tg_ids=skipped_tg_ids, truncated=truncated,
                chunk_count=chunk_count)
    try:
        return _validate(data, id_space, base)
    except Exception:  # pragma: no cover - защитная ветка
        logger.warning("L1 contract: internal error — fail-closed",
                       exc_info=True)
        return invalid_result(REASON_INTERNAL_ERROR, **base)


def _validate(data, id_space: IdSpace, base: dict) -> L1Result:
    if not isinstance(data, dict):
        return invalid_result(REASON_BAD_TYPE, **base)

    # 1. Top-level: ровно 5 известных ключей (строгая политика D5).
    if set(data) - TOP_LEVEL_FIELDS:
        return invalid_result(REASON_UNKNOWN_FIELD, **base)

    response_mode, cover_prompt = service_fields(data)
    base = dict(base, response_mode=response_mode, cover_prompt=cover_prompt)

    # 2. schema_version: строго int == 1 (bool — не int).
    if not isinstance(data.get("schema_version"), int) \
            or isinstance(data.get("schema_version"), bool) \
            or data.get("schema_version") != SCHEMA_VERSION:
        return invalid_result(REASON_BAD_SCHEMA_VERSION, **base)

    threads = data.get("threads")
    unassigned = data.get("unassigned_message_ids")
    if not isinstance(threads, list) or not isinstance(unassigned, list):
        return invalid_result(REASON_BAD_TYPE, **base)
    if len(threads) > MAX_THREADS:
        return invalid_result(REASON_TOO_MANY_THREADS, **base)

    # 3. Треды/факты: структура, типы, лимиты, существование id.
    canonical_threads: list[dict] = []
    seen_ids: dict[int, int] = {}       # tg id → индекс треда
    total_facts = 0
    for thread in threads:
        if not isinstance(thread, dict):
            return invalid_result(REASON_BAD_TYPE, **base)
        if set(thread) - THREAD_FIELDS:
            return invalid_result(REASON_UNKNOWN_FIELD, **base)
        thread_id = thread.get("thread_id")
        if not isinstance(thread_id, str) or not THREAD_ID_RE.match(thread_id):
            return invalid_result(REASON_INVALID_THREAD_ID, **base)
        topic = _valid_topic(thread.get("topic"))
        if topic is None:
            return invalid_result(REASON_INVALID_TOPIC, **base)
        raw_ids = thread.get("message_ids")
        if not isinstance(raw_ids, list):
            return invalid_result(REASON_BAD_TYPE, **base)
        message_ids: list[int] = []
        for mid in raw_ids:
            value = _as_int(mid)
            if value is None:
                return invalid_result(REASON_BAD_TYPE, **base)
            if not id_space.contains(value):
                return invalid_result(REASON_UNKNOWN_MESSAGE_ID, **base)
            if value not in message_ids:
                message_ids.append(value)
        # Один id — ровно в одном треде (дубли внутри треда детерминированно
        # дедуплицируются, между тредами — fail-closed).
        thread_index = len(canonical_threads)
        for mid in message_ids:
            if mid in seen_ids:
                return invalid_result(
                    REASON_MESSAGE_IN_MULTIPLE_THREADS, **base)
            seen_ids[mid] = thread_index
        facts_raw = thread.get("facts")
        if not isinstance(facts_raw, list):
            return invalid_result(REASON_BAD_TYPE, **base)
        if len(facts_raw) > MAX_FACTS_PER_THREAD:
            return invalid_result(REASON_TOO_MANY_FACTS, **base)
        facts: list[dict] = []
        for fact in facts_raw:
            if not isinstance(fact, dict):
                return invalid_result(REASON_BAD_TYPE, **base)
            if set(fact) - FACT_FIELDS:
                return invalid_result(REASON_UNKNOWN_FIELD, **base)
            text = _valid_fact_text(fact.get("text"))
            if text is None:
                return invalid_result(REASON_INVALID_FACT, **base)
            evidence_raw = fact.get("evidence_message_ids")
            if not isinstance(evidence_raw, list):
                return invalid_result(REASON_BAD_TYPE, **base)
            evidence: list[int] = []
            for eid in evidence_raw:
                value = _as_int(eid)
                if value is None:
                    return invalid_result(REASON_BAD_TYPE, **base)
                if value not in message_ids:
                    return invalid_result(
                        REASON_EVIDENCE_NOT_IN_THREAD, **base)
                if value not in evidence:
                    evidence.append(value)
            facts.append({"text": text, "evidence_message_ids": evidence,
                          "_key": _fact_key(text)})
        total_facts += len(facts)
        canonical_threads.append({"topic": topic, "message_ids": message_ids,
                                  "facts": facts})
    if total_facts > MAX_FACTS_TOTAL:
        return invalid_result(REASON_TOO_MANY_FACTS_TOTAL, **base)

    # 4. unassigned: существование id + отсутствие конфликта с тредами.
    unassigned_ids: list[int] = []
    for mid in unassigned:
        value = _as_int(mid)
        if value is None:
            return invalid_result(REASON_BAD_TYPE, **base)
        if not id_space.contains(value):
            return invalid_result(REASON_UNKNOWN_MESSAGE_ID, **base)
        if value in seen_ids:
            return invalid_result(REASON_UNASSIGNED_CONFLICT, **base)
        if value not in unassigned_ids:
            unassigned_ids.append(value)

    # 5. Канонизация: ASC (timestamp, message_id); перенумерация; дедуп
    #    фактов с объединением evidence; авто-unassigned для остальных id.
    canonical: list[dict] = []
    for thread in canonical_threads:
        message_ids = sorted(thread["message_ids"], key=id_space.sort_key)
        merged: dict[str, dict] = {}
        for fact in thread["facts"]:
            key = fact["_key"]
            item = merged.get(key)
            if item is None:
                merged[key] = {"text": fact["text"],
                               "evidence_message_ids": list(
                                   fact["evidence_message_ids"])}
            else:
                for eid in fact["evidence_message_ids"]:
                    if eid not in item["evidence_message_ids"]:
                        item["evidence_message_ids"].append(eid)
        facts = []
        for item in merged.values():
            item["evidence_message_ids"] = sorted(
                item["evidence_message_ids"], key=id_space.sort_key)
            facts.append(item)
        canonical.append({"topic": thread["topic"], "message_ids": message_ids,
                          "facts": facts})

    order = []
    for index, thread in enumerate(canonical):
        first = id_space.sort_key(thread["message_ids"][0]) \
            if thread["message_ids"] else (0, 0)
        order.append((first, index))
    canonical = [canonical[index] for _key, index in sorted(order)]

    mentioned = set(seen_ids) | set(unassigned_ids)
    auto_added = sorted((mid for mid in id_space.ids if mid not in mentioned),
                        key=id_space.sort_key)
    auto_unassigned = len(auto_added)
    unassigned_ids = sorted(set(unassigned_ids) | set(auto_added),
                            key=id_space.sort_key)

    threads_out = []
    for number, thread in enumerate(canonical, start=1):
        threads_out.append({
            "thread_id": THREAD_ID_TEMPLATE % number,
            "topic": thread["topic"],
            "message_ids": thread["message_ids"],
            "facts": thread["facts"],
        })
    facts_count = sum(len(t["facts"]) for t in threads_out)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "threads": threads_out,
        "unassigned_message_ids": unassigned_ids,
    }
    # Служебные поля (D2) — в том же JSON, но НЕ в L2-контент (изоляция).
    if response_mode:
        payload["response_mode"] = response_mode
    if cover_prompt:
        payload["cover_prompt"] = cover_prompt

    if not threads_out:
        return empty_result(threads=0, facts=0, auto_unassigned=auto_unassigned,
                            **base)

    logger.info(
        "L1 contract: validated | threads=%d | facts=%d | auto_unassigned=%d",
        len(threads_out), facts_count, auto_unassigned)
    return _make_result(
        STATUS_OK, payload=payload, threads=len(threads_out),
        facts=facts_count, auto_unassigned=auto_unassigned, **base)
