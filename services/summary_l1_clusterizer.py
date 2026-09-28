"""S3 round1026 (ADR-1026-5 D1/D2/D4/D5) — L1 «Кластеризатор» (§92–§95).

ASAP-2.1 (ADR-1028-1 D1/D2): вход §92 строится из ПОЛНОГО окна (heuristic
prefilter S1 удалён из live-пути); ``build_l1_payload`` перенесён сюда из
распущенного S2-модуля (единственный живой символ того
модуля). Технические примитивы нарезки/оценки объёма — из
``summary_hybrid_budget`` (нейтральный модуль бюджета Hybrid).

**Автономный модуль** (живой путь — ``summary_generator._run_hybrid_l2``):
вход §92 (``build_l1_payload``) → упаковка §93-фрагментов в **один** вход →
**ровно 1 LLM-вызов** L1 → парсер → валидатор §95 (``summary_l1_contract``)
→ fail-closed ``L1Result``.

Инварианты (ADR-1026-5 + ADR-1028-1):
  * **ровно 1 вызов L1-слоя** (целевой пайплайн = 2: L1+L2; третий вызов —
    блокер). Фрагменты §93 (``estimate_and_split``, overlap=1) упаковываются
    в один вход (ASC, дедуп, маркеры границ); при нехватке бюджета —
    детерминированный ``truncated`` + ``skipped_ids`` + WARN («не резать
    молча», последние сообщения сохраняются всегда). Мультивызовый chunk-merge
    — **BLOCKED**;
  * **пространства ID явные** (D5): ``Fragment.message_ids`` — DB ``id``;
    для L1 они конвертируются через **таблицу соответствия строк окна**
    (``id`` ↔ ``tg_message_id``); пропуск/неоднозначность → ``invalid``
    ``id_space_mismatch`` (без «конвертации на глаз» и фабрикации id);
  * **L1 не пишет саммари** (§94): только темы/факты/ID строгого JSON §95;
  * **слот §82 — env-only** (D4): ``SUMMARY_L1_BASE_URL``/``SUMMARY_L1_MODEL_NAME``
    /``SUMMARY_L1_API_KEY`` (ClassVar, Δ каталога=0), hot-first резолв,
    пусто → глобальная основная модель (наследование ≠ аварийное
    резервирование);
  * **eviction чисто технический** (ADR-1028-1 D1): ключ
    ``(reply_protected, timestamp, db_id)`` — БЕЗ весового члена S1;
  * **логи §108/§109 аддитивны и R17-safe**: ``L1_START``/``L1_COMPLETE``/
    ``L1_ERROR`` — только числа/коды/id (без ключей, текстов и сырого ответа);
    узлы ExecutionGraph НЕ эмитятся (их эмитит S8).
"""
from __future__ import annotations

import dataclasses
import json
import logging
import time

from config.settings import settings
from services.llm_client import LLMBadResponseError, LLMError
from services.prompt_style_blocks import resolve_prompt
from services.summary_hybrid_budget import (
    estimate_and_split,
    hybrid_input_budget,
    hybrid_output_reserve_tokens,
    resolve_hybrid_context_budget,
)
from services.summary_l1_contract import (
    REASON_BAD_SCHEMA_VERSION,
    REASON_BAD_TYPE,
    REASON_EMPTY_RESPONSE,
    REASON_ID_SPACE_MISMATCH,
    REASON_INTERNAL_ERROR,
    REASON_INVALID_FACT,
    REASON_INVALID_JSON,
    REASON_INVALID_THREAD_ID,
    REASON_INVALID_TOPIC,
    REASON_L1_USELESS_AFTER_REPAIR,
    REASON_LLM_ERROR,
    REASON_LLM_TIMEOUT,
    REASON_OK,
    REASON_UNKNOWN_FIELD,
    REASON_UNKNOWN_MESSAGE_ID,
    STATUS_INVALID,
    STATUS_OK,
    STATUS_TRUNCATED,
    IdSpace,
    L1Result,
    build_id_space,
    empty_result,
    error_result,
    invalid_result,
    parse_l1_response,
    validate_l1_response,
)
from services.summary_l1_repair import repair_l1
from services.summary_prompts import SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT
# S7 (ADR-1026-9 D6/SC-07): §109-детали ошибки — http_status/attempts.
from services.summary_run_log import attempts_of, http_status_of
from services.token_counter import count_tokens, resolve_chat_limit

logger = logging.getLogger(__name__)

MODULE = "summary"
STEP = "l1_clusterizer"
PROMPT_PG_KEY = "prompts.summary_l1_clusterizer_system_prompt"

# ASAP-2 §11 (контракт (g)): бюджет входа L1 — ТОЛЬКО hybrid-ключи
# `limits.summary_hybrid_context_*` (единая точка
# `summary_hybrid_budget.resolve_hybrid_context_budget`; legacy
# `limits.summary_max_context_*` в Hybrid не читаются). Константы ниже —
# исторический паритет дефолтов (30000 токенов ==
# `_SUMMARY_CONTEXT_TOKEN_DEFAULT` summary_generator; масштаб hybrid-ключа
# тот же), потребителями бюджета больше не являются.
L1_CONTEXT_TOKEN_DEFAULT = 30000
CHARS_ENV = "SUMMARY_MAX_CONTEXT_CHARS"

# Маркер границы §93-фрагмента в ЕДИНОМ входе L1 (не отдельный вызов).
CHUNK_MARKER_TEMPLATE = "=== ЧАСТЬ {index}/{total} ==="

# Оценка накладных расходов маркеров при упаковке (детерминированно).
_MARKER_OVERHEAD_TOKENS = count_tokens(CHUNK_MARKER_TEMPLATE.format(
    index=999, total=999))

# ── ASAP-2 round1027 (контракт (c)/§15): correction retry ПОСЛЕ repair ─────
# Retryable-набор — причины ПОСЛЕ deterministic repair + validate: классы
# формата/структуры/ссылок ответа модели и «useless после ремонта». Жёсткие
# лимиты контракта (too_many_*) — переполнение, НЕ retryable (→ LEVEL-2);
# транспорт (LLMError/LLMTimeoutError) — error_result без ретрая;
# id_space_mismatch/internal_error — наши баги, ретрай бессмысленен.
# `message_in_multiple_threads` в v2 НЕ СУЩЕСТВУЕТ (пересечение — норма).
_RETRYABLE_REASONS: frozenset[str] = frozenset({
    REASON_INVALID_JSON,
    REASON_EMPTY_RESPONSE,
    REASON_BAD_TYPE,
    REASON_UNKNOWN_FIELD,
    REASON_BAD_SCHEMA_VERSION,
    REASON_INVALID_THREAD_ID,
    REASON_INVALID_TOPIC,
    REASON_INVALID_FACT,
    REASON_L1_USELESS_AFTER_REPAIR,
    REASON_UNKNOWN_MESSAGE_ID,   # defense: repair должен был спасти
})

# Максимум id в correction-тексте (§15:2496–2499; списки id — ТОЛЬКО в
# промпт второй попытки, в логи уходят счётчики — R17).
_CORRECTION_ID_CAP = 20


def _hot_flag(key: str, env_default) -> bool:
    """Hot-first резолв recovery-тумблера (паттерн `_hybrid_l2_enabled`:
    PG-ключ каталога → env ClassVar-дефолт; fail-open к env)."""
    try:
        from services import hot_config as hot
        return bool(hot.get(key, env_default))
    except Exception:  # pragma: no cover - защитная ветка
        return bool(env_default)


def _repair_enabled() -> bool:
    return _hot_flag("flags.summary_hybrid_l1_repair_enabled",
                     bool(getattr(settings, "SUMMARY_L1_REPAIR_ENABLED", True)))


def _retry_enabled() -> bool:
    return _hot_flag("flags.summary_hybrid_l1_retry_enabled",
                     bool(getattr(settings, "SUMMARY_L1_RETRY_ENABLED", True)))


def _collect_unknown_ids(data, id_space, cap=_CORRECTION_ID_CAP) -> list:
    """Числовые message_id, выдуманные моделью (для correction-текста;
    только id, без контента — R17-safe в промпте, в логи НЕ пишутся)."""
    unknown: list = []
    try:
        for thread in (data or {}).get("threads") or []:
            if not isinstance(thread, dict):
                continue
            collections = [thread.get("message_ids") or []]
            for fact in thread.get("facts") or []:
                if isinstance(fact, dict):
                    collections.append(fact.get("evidence_message_ids") or [])
            for collection in collections:
                for mid in collection:
                    value = mid if isinstance(mid, int) and not isinstance(
                        mid, bool) else None
                    if value is not None and not id_space.contains(value) \
                            and value not in unknown:
                        unknown.append(value)
        for mid in (data or {}).get("unassigned_message_ids") or []:
            value = mid if isinstance(mid, int) and not isinstance(
                mid, bool) else None
            if value is not None and not id_space.contains(value) \
                    and value not in unknown:
                unknown.append(value)
    except Exception:  # pragma: no cover - защитная ветка
        return unknown[:cap]
    return unknown[:cap]


def _correction_block(reason: str, *, unknown_ids: list,
                      useless_reason: str = "") -> str:
    """Correction-блок второй попытки (текст контракта (c)): append к
    исходному user-контенту; system-канон не дублируется; §15:2496–2499."""
    lines = [f"ПРЕДЫДУЩИЙ ОТВЕТ ОТКЛОНЁН: {reason}."]
    if reason in (REASON_UNKNOWN_MESSAGE_ID, REASON_L1_USELESS_AFTER_REPAIR) \
            and useless_reason == "mass_unknown_ids":
        lines.append(
            "неизвестные message_id ["
            + ", ".join(str(value) for value in unknown_ids)
            + "]. Используй ТОЛЬКО message_id из входных данных. "
              "Не выдумывай идентификаторы. Do not invent message ids.")
    if reason == REASON_L1_USELESS_AFTER_REPAIR:
        lines.append(
            "после ремонта не осталось пригодных тем/фактов (причина: "
            f"{useless_reason or '-'}). Верни структуру, опирающуюся только "
            "на реальные message_id. Не выдумывай идентификаторы. "
            "Do not invent message ids.")
    elif reason == REASON_UNKNOWN_MESSAGE_ID:
        lines.append(
            "неизвестные message_id ["
            + ", ".join(str(value) for value in unknown_ids)
            + "]. Используй ТОЛЬКО message_id из входных данных. "
              "Не выдумывай идентификаторы. Do not invent message ids.")
    elif reason in (REASON_INVALID_JSON, REASON_EMPTY_RESPONSE,
                    REASON_BAD_SCHEMA_VERSION, REASON_BAD_TYPE,
                    REASON_UNKNOWN_FIELD):
        lines.append(
            "верни СТРОГО валидный JSON-объект по схеме (schema_version: 2), "
            "без текста вокруг.")
    else:
        # invalid_thread_id / invalid_topic / invalid_fact — структура цела,
        # нарушены текстовые/ссылочные требования схемы.
        lines.append(
            "верни строго валидный JSON-объект по схеме (schema_version: 2): "
            "thread_id вида thread_NNN; topic — одна строка ≤200 символов; "
            "каждый fact — атомарный ≤500 символов с ≥1 evidence_message_ids "
            "из входных данных, без системных тегов и markdown-заголовков.")
    lines.append("Верни исправленный JSON.")
    return "\n".join(lines)


def _build_correction_messages(messages, reason: str, *, unknown_ids: list,
                               useless_reason: str = "") -> list:
    """Сообщения второй попытки: system + исходный user + correction-блок
    (append; system-канон НЕ дублируется — контракт (c))."""
    corrected = [dict(messages[0])]
    user = dict(messages[1])
    user["content"] = (str(user.get("content") or "")
                       + "\n\n" + _correction_block(
                           reason, unknown_ids=unknown_ids,
                           useless_reason=useless_reason))
    corrected.append(user)
    return corrected


class IdSpaceMismatch(ValueError):
    """DB ``id`` ↔ TG ``message_id``: пропуск/неоднозначность (§5.2, D5)."""


@dataclasses.dataclass(frozen=True)
class L1Slot:
    """Резолв слота summary L1 §82 (env-only, D4)."""

    base_url: str
    model: str
    api_key: str
    dedicated: bool


@dataclasses.dataclass(frozen=True)
class PackResult:
    """Результат упаковки §92/§93 в один вход L1."""

    payload: list                 # §92-элементы (ASC, дедуп)
    chunk_count: int
    chunk_starts: tuple           # TG id первых сообщений фрагментов 2..N
    skipped_ids: tuple            # DB id (пространство S1/S2)
    skipped_tg_ids: tuple         # TG message_id (пространство §95)
    truncated: bool
    estimated_tokens: int
    kind: str
    limit: int
    source_count: int


# ── Доступ к полям строки окна (dict | sqlite3.Row | объект) ───────────────

def _row_get(row, name):
    if row is None:
        return None
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return getattr(row, name, None)


def _row_id(row):
    return _row_get(row, "id")


def _row_tg(row):
    return _row_get(row, "tg_message_id")


def _row_ts(row):
    try:
        return int(_row_get(row, "timestamp") or 0)
    except (TypeError, ValueError):
        return 0


def _row_text(row):
    value = _row_get(row, "text")
    return "" if value is None else str(value)


def _id_key(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _sort_rows(rows):
    """ASC-хронология с тай-брейком ``(timestamp, DB id)`` (§90/§93)."""
    return sorted(rows or [], key=lambda r: (_row_ts(r), _id_key(_row_id(r))))


def _payload_item(row, chat_id) -> dict:
    """Один §92-элемент (тот же канон, что ``build_l1_payload``) — для
    serialized-оценки бюджета упаковки (Q5)."""
    return build_l1_payload([row], chat_id)[0]


def _serialized_len(item, kind: str) -> int:
    """Оценка ЭЛЕМЕНТА §92 по реальному serialized JSON (ASAP-2 Q5/контракт
    (k): serialized_chars/serialized_tokens честные): имена полей/типы
    учитываются (раньше — только text, ~15–20 токенов/сообщение терялось)."""
    text = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
    return count_tokens(text) if kind == "tokens" else len(text)


def _row_reply_to(row):
    value = _row_get(row, "reply_to_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# ── ASAP-2.1 (ADR-1028-1 D1, контракт (a)): ЧИСТО ТЕХНИЧЕСКИЙ eviction ─────
# Весовой член S1 УДАЛЁН: модуль больше не решает,
# «какие сообщения кажутся важными». Ключ вытеснения —
# (reply_protected, timestamp, db_id): reply-цепочки (физическая связность
# пакета) вытесняются последними, внутри приоритета — старые раньше свежих.

def _eviction_key(row, *, kept_tg: set, children_by_tg: dict):
    """Ключ вытеснения ASC ``(reply_protected, timestamp, db_id)``:
    reply-защита — целостность reply-цепочек внутри пакета (физическая
    связность, НЕ «важность»); дальше — старый контекст вытесняется первым."""
    tg = _row_tg(row)
    reply = _row_reply_to(row)
    protected = 1 if ((reply is not None and reply in kept_tg)
                      or (tg is not None and children_by_tg.get(tg, 0) > 0)) \
        else 0
    return (protected, _row_ts(row), _id_key(_row_id(row)))


# ── §92: структурированный вход L1 (ASAP-2.1: перенос из распущенного
#    S2-модуля, сигнатура без изменений) ──────────

_L1_FIELDS = (
    "message_id",
    "chat_id",
    "timestamp",
    "author_id",
    "display_name",
    "text",
    "reply_to_id",
    "message_type",
)


def build_l1_payload(rows, chat_id) -> list:
    """Структурированные сообщения §92 для L1-кластеризатора.

    Используются **только фактически доступные** поля строки окна:
    ``message_id ← tg_message_id``, ``author_id ← user_id``,
    ``display_name ← author_name``, ``message_type ← media_type``,
    ``reply_to_id``, ``timestamp``, ``text``; ``chat_id`` — из контекста
    запуска. Отсутствующие метаданные не выдумываются: ``mentions`` (поля в
    окне нет) в элемент не попадает вовсе.
    """
    payload: list = []
    for row in rows or []:
        item = {
            "message_id": _row_tg(row),
            "chat_id": chat_id,
            "timestamp": _row_get(row, "timestamp"),
            "author_id": _row_get(row, "user_id"),
            "display_name": _row_get(row, "author_name"),
            "text": _row_get(row, "text"),
            "reply_to_id": _row_get(row, "reply_to_id"),
            "message_type": _row_get(row, "media_type"),
        }
        mentions = _row_get(row, "mentions")
        if mentions is not None:
            item["mentions"] = mentions
        payload.append(item)
    return payload


# ── §93: упаковка фрагментов в один вход (без второго вызова) ──────────────

def build_db_tg_map(rows) -> dict:
    """Явная таблица соответствия DB ``id`` → TG ``message_id`` (§5.2).

    Неоднозначность (один DB ``id`` с разными TG id) или отсутствие любого
    из полей → :class:`IdSpaceMismatch` (fail-closed; «на глаз» запрещено).
    """
    mapping: dict = {}
    for row in rows or []:
        db_id = _row_id(row)
        tg_id = _row_tg(row)
        if db_id is None or tg_id is None:
            raise IdSpaceMismatch(
                f"row without id/tg_message_id: db={db_id!r} tg={tg_id!r}")
        if db_id in mapping and mapping[db_id] != tg_id:
            raise IdSpaceMismatch(
                f"ambiguous db id {db_id!r}: "
                f"{mapping[db_id]!r} vs {tg_id!r}")
        mapping[db_id] = tg_id
    return mapping


def pack_l1_input(rows, chat_id, *, token_limit=None, char_limit=None,
                  marker_overhead: bool = True) -> PackResult:
    """§92/§93: собрать **один** вход L1 из восстановленного окна.

    Оценка объёма — существующий ``estimate_and_split`` (overlap=1, последний
    фрагмент всегда заканчивается последним сообщением); фрагменты
    объединяются в один вход (дедуп DB id, ASC, маркеры границ).     Итоговый
    бюджет-тест — по РЕАЛЬНОМУ serialized §92-элементу (ASAP-2 Q5:
    ``count_tokens(json.dumps(item))``, имена полей учтены), а не по голому
    тексту. Если итог не влезает — ЧИСТО ТЕХНИЧЕСКИЙ eviction (ASAP-2.1
    ADR-1028-1 D1): victim = min ASC ``(reply_protected, timestamp, id)`` —
    сначала старый контекст без reply-связей; reply-цепочки вытесняются
    последними; ПОСЛЕДНЕЕ сообщение сохраняется всегда (§93); любое
    вытеснение → ``truncated=True`` + ``skipped_ids`` + WARN («не резать
    молча»). DB id → TG message_id — только через :func:`build_db_tg_map`.
    """
    rows_sorted = _sort_rows(list(rows or []))
    fragments, budget = estimate_and_split(
        rows_sorted, token_limit=token_limit, char_limit=char_limit)
    kind = str(budget.get("kind") or "tokens")
    limit = int(budget.get("limit") or 0)

    if fragments is None:
        used = list(rows_sorted)
        chunk_count = 1 if rows_sorted else 0
        chunk_starts: tuple = ()
    else:
        db_tg = build_db_tg_map(rows_sorted)
        used_ids: set = set()
        starts: list = []
        for index, fragment in enumerate(fragments):
            for db_id in fragment.message_ids:
                if db_id not in db_tg:
                    raise IdSpaceMismatch(
                        f"fragment id {db_id!r} absent in window rows")
                used_ids.add(db_id)
            if index > 0 and fragment.message_ids:
                starts.append(db_tg[fragment.message_ids[0]])
        used = [row for row in rows_sorted if _row_id(row) in used_ids]
        chunk_count = len(fragments)
        chunk_starts = tuple(starts)

    unit = lambda row: _serialized_len(  # noqa: E731 - локальный алиас
        _payload_item(row, chat_id), kind)  # serialized-учёт §92-элемента (Q5)
    units = [unit(row) for row in used]
    overhead = _MARKER_OVERHEAD_TOKENS * max(0, chunk_count - 1) \
        if (marker_overhead and kind == "tokens") else 0
    if marker_overhead and kind != "tokens":
        overhead = len(CHUNK_MARKER_TEMPLATE.format(index=99, total=99)) \
            * max(0, chunk_count - 1)
    total = sum(units) + overhead

    truncated = False
    skipped_rows: list = []
    if limit and total > limit:
        # ASAP-2.1 (ADR-1028-1 D1): eviction чисто технический —
        # victim = min ASC (reply_protected, timestamp, id);
        # последнее сообщение сохраняется всегда (§93); любое вытеснение →
        # truncated + skipped_ids + WARN (без молчаливого среза).
        truncated = True
        while len(used) > 1 and total > limit:
            kept_tg = {_row_tg(r) for r in used if _row_tg(r) is not None}
            children: dict = {}
            for r in used:
                reply = _row_reply_to(r)
                if reply is not None:
                    children[reply] = children.get(reply, 0) + 1
            best_key = None
            best_index = 0
            # последнее сообщение (индекс len-1) — неприкосновенно (§93).
            for index in range(len(used) - 1):
                key = _eviction_key(used[index], kept_tg=kept_tg,
                                    children_by_tg=children)
                if best_key is None or key < best_key:
                    best_key = key
                    best_index = index
            removed = used.pop(best_index)
            units.pop(best_index)
            total -= _serialized_len(_payload_item(removed, chat_id), kind)
            skipped_rows.append(removed)

    skipped_ids = tuple(_row_id(r) for r in skipped_rows)
    skipped_tg = tuple(_row_tg(r) for r in skipped_rows)
    payload = build_l1_payload(used, chat_id)
    return PackResult(
        payload=payload, chunk_count=chunk_count, chunk_starts=chunk_starts,
        skipped_ids=skipped_ids, skipped_tg_ids=skipped_tg,
        truncated=truncated, estimated_tokens=total, kind=kind, limit=limit,
        source_count=len(rows_sorted))


def build_l1_user_content(payload_items, chunk_count=1,
                          chunk_starts: tuple = ()) -> str:
    """Детерминированный user-контент L1: ASC-строки §92 + маркеры границ.

    Каждое сообщение — компактный JSON-объект (поля §92, порядок фиксирован
    ``build_l1_payload``); маркеры ``=== ЧАСТЬ k/N ===`` — только границы
    исходных §93-фрагментов (не темы, не отдельные вызовы).
    """
    items = list(payload_items or [])
    lines = [f"СООБЩЕНИЯ ЧАТА (хронология ASC; message_id — Telegram id), "
             f"всего {len(items)}:"]
    total = max(1, int(chunk_count or 1))
    pending_starts = [mid for mid in (chunk_starts or ())]
    part = 1
    for item in items:
        mid = item.get("message_id") if isinstance(item, dict) else None
        if part < total and pending_starts and mid == pending_starts[0]:
            pending_starts.pop(0)
            part += 1
            lines.append(CHUNK_MARKER_TEMPLATE.format(index=part, total=total))
        lines.append(json.dumps(item, ensure_ascii=False,
                                separators=(",", ":")))
    return "\n".join(lines)


# ── Слот §82 (env-only, D4) ────────────────────────────────────────────────

def resolve_l1_slot(*, hot_get=None, settings_obj=None) -> L1Slot:
    """Согласованная пара (``base_url``, ``model``) + ключ слоя summary L1.

    Приоритет рантайма — hot-first (forward-compatible с будущими PG-ключами
    ``models.summary_l1_*``/``keys.summary_l1_api_key``, S5), дефолты —
    env-only ClassVars ``SUMMARY_L1_*`` (Δ каталога = 0). Пустое поле пары
    добирается из глобальной основной модели; ``dedicated=True``, если задан
    хотя бы один из трёх env-ключей слоя. Секрет не логируется (R17).
    """
    if hot_get is None:
        from services import hot_config as hot
        hot_get = hot.get
    st = settings_obj or settings

    def _read(key: str, field: str) -> str:
        return str(hot_get(key, getattr(st, field, "")) or "").strip()

    raw_base = _read("models.summary_l1_base_url", "SUMMARY_L1_BASE_URL")
    raw_model = _read("models.summary_l1_model_name", "SUMMARY_L1_MODEL_NAME")
    raw_key = _read("keys.summary_l1_api_key", "SUMMARY_L1_API_KEY")
    global_base = _read("models.llm_base_url", "LLM_BASE_URL")
    global_model = _read("models.llm_model_name", "LLM_MODEL_NAME")
    global_key = str(hot_get("keys.llm_api_key",
                             getattr(st, "LLM_API_KEY", "")) or "").strip()
    return L1Slot(
        base_url=raw_base or global_base,
        model=raw_model or global_model,
        api_key=raw_key or global_key,
        dedicated=bool(raw_base or raw_model or raw_key))


def resolve_l1_budget(*, hot_get=None, settings_obj=None) -> tuple[str, int]:
    """Бюджет входа L1 — hybrid-ключи ``limits.summary_hybrid_context_*``
    (ASAP-2 §11/контракт (g): полная separация Legacy/Hybrid; единая точка
    ``resolve_hybrid_context_budget``). Токенный приоритет + аварийный
    chars-fallback — штатная семантика ``resolve_chat_limit``;
    per-chat-резолв — при врезке в генераторе (ctx-слой `_chat_limit`).
    """
    return resolve_hybrid_context_budget(hot_get=hot_get,
                                         settings_obj=settings_obj)


def provider_host(base_url: str) -> str:
    """R17-safe провайдер для логов: только host (без пути/ключа/query)."""
    try:
        from urllib.parse import urlsplit
        parts = urlsplit(str(base_url or ""))
        return parts.hostname or ""
    except Exception:  # pragma: no cover - защитная ветка
        return ""


# ── Вызов LLM: ровно один, через слот или глобальную модель ────────────────

def _extract_usage(value):
    """(in, out) токены из usage-словаря провайдера; иначе (None, None)."""
    if not isinstance(value, dict):
        return None, None
    try:
        prompt = int(value.get("prompt_tokens"))
    except (TypeError, ValueError):
        prompt = None
    try:
        completion = int(value.get("completion_tokens"))
    except (TypeError, ValueError):
        completion = None
    return prompt, completion


def _normalise_call_result(value):
    """Контракт кастомного ``llm_call``: ``str`` либо ``(str, usage|None)``."""
    if isinstance(value, tuple) and len(value) == 2:
        return str(value[0] or ""), value[1]
    return str(value or ""), None


async def _dedicated_generate(llm, messages, slot: L1Slot) -> tuple[str, dict]:
    """Выделенный слот §82 через существующий транзитный канал LLMClient.

    Контракт S3: ``llm_client`` не переписывается (T-3266 — «только чтение
    контракта»), поэтому per-call ``base_url``/``model``/``api_key`` идут
    через тот же retry/fallback-канал, что ``generate_worker``/``generate``:
    ошибка dedicated уходит в **существующую политику** ``LLM_FALLBACK_*``
    (``_fallback_with_retries``), БЕЗ подмены на глобальную модель. Публичный
    метод клиента — кандидат на S5 (врезка) отдельной санкцией.
    """
    payload = {"model": slot.model, "messages": messages}
    try:
        response = await llm._post(  # noqa: SLF001 - документированный мост S3
            "/chat/completions", payload, api_key=slot.api_key,
            base_url=slot.base_url)
    except LLMError as exc:
        fallback = getattr(llm, "_fallback_with_retries", None)
        active = bool(getattr(llm, "_fallback_active", False))
        if fallback is None or not active or isinstance(exc, LLMBadResponseError):
            raise
        response = await fallback(payload)
        if response is None:
            raise exc from None
    try:
        data = response.json()
    except ValueError as exc:
        raise LLMBadResponseError("L1 dedicated: invalid JSON response") from exc
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMBadResponseError(
            "L1 dedicated: no choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise LLMBadResponseError("L1 dedicated: empty content")
    return content, (data.get("usage") if isinstance(data, dict) else None)


def _make_llm_call(llm, slot: L1Slot, correlation_id):
    """Собрать async-callable L1 (ровно один вызов на запуск)."""
    if not slot.dedicated:
        async def _call(messages):
            return await llm.generate(messages, module=MODULE, step=STEP,
                                      correlation_id=correlation_id)
        return _call

    async def _call_dedicated(messages):
        return await _dedicated_generate(llm, messages, slot)
    return _call_dedicated


def _effective_model(llm, slot: L1Slot) -> str:
    if slot.dedicated:
        return slot.model
    return str(getattr(llm, "_chat_model", "") or slot.model)


def _effective_base_url(llm, slot: L1Slot) -> str:
    if slot.dedicated:
        return slot.base_url
    return str(getattr(llm, "_base_url", "") or slot.base_url)


# ── §109: логи (аддитивные, R17-safe) ──────────────────────────────────────

def _log_start(*, correlation_id, chat_id, source_count, estimated_tokens,
               chunk_count, model, base_url, dedicated) -> None:
    logger.info(
        "L1_START | run_id=%s | chat_id=%s | messages=%d | tokens_est=%d | "
        "chunks=%d | model=%s | provider=%s | dedicated=%s",
        correlation_id or "none", chat_id, source_count, estimated_tokens,
        chunk_count, model or "-", provider_host(base_url) or "-",
        bool(dedicated))


def _log_complete(*, correlation_id, chat_id, result: L1Result, model,
                  base_url, tokens_in, tokens_out, tokens_estimated,
                  chunk_count, attempts: int = 1) -> None:
    # ASAP-2 hotfix round1027: аддитивное поле attempts (1 — single-shot,
    # 2 — была повторная попытка; R17-safe число).
    logger.info(
        "L1_COMPLETE | run_id=%s | chat_id=%s | provider=%s | model=%s | "
        "tokens_in=%s | tokens_out=%s | tokens_estimated=%s | threads=%d | "
        "facts=%d | chunks=%d | auto_unassigned=%d | skipped=%d | "
        "truncated=%s | attempts=%d | status=%s | invalid_reason=%s | "
        "duration_ms=%.0f",
        correlation_id or "none", chat_id, provider_host(base_url) or "-",
        model or "-", tokens_in if tokens_in is not None else "-",
        tokens_out if tokens_out is not None else "-", bool(tokens_estimated),
        result.threads_count, result.facts_count, chunk_count,
        result.auto_unassigned_count, len(result.skipped_ids),
        bool(result.truncated), max(int(attempts), 1), result.status,
        result.invalid_reason or "-", result.duration_ms)


def _log_error(*, correlation_id, chat_id, model, base_url, reason, error_type,
               duration_ms, http_status=None, attempts=None) -> None:
    logger.warning(
        "L1_ERROR | run_id=%s | chat_id=%s | provider=%s | model=%s | "
        "error=%s | reason=%s | http_status=%s | attempts=%s | duration_ms=%.0f",
        correlation_id or "none", chat_id, provider_host(base_url) or "-",
        model or "-", error_type or "-", reason or "-",
        http_status if http_status is not None else "-",
        attempts if attempts is not None else "-", duration_ms)


# ── Ядро запуска L1 (без врезки в живой путь) ──────────────────────────────

async def run_l1(llm=None, rows=None, chat_id=None, *, correlation_id=None,
                 budget=None, system_prompt=None, llm_call=None,
                 focus_block=None) -> L1Result:
    """Один прогон L1: §92-вход → §93-упаковка → LLM-вызов(ы) → §95-v2.

    ``llm`` — LLMClient (или совместимый мок); ``llm_call`` — инъекция канала
    (S5/тесты). ``budget`` — ``(kind, limit)``; ``None`` → hybrid-ключи
    ``limits.summary_hybrid_context_*`` через ``resolve_hybrid_context_budget``
    (ASAP-2 §11/D7: Q5-формула safe−system−markers−reserve; legacy
    ``limits.summary_max_context_*`` не читаются; явный budget из тестов
    применяется как есть). ``focus_block`` — необязательный префикс
    user-контента (S5/§80: focus «/summary про X» на ON-пути — как в legacy;
    ``None``/пусто → вход байт-в-байт прежний). Fail-closed: любое
    исключение/``LLMError`` → ``error``/``invalid`` с кодом причины,
    ``payload=None`` (в L2 не передаётся).

    ASAP-2 round1027 (§15/§16, контракты (b)/(c)): порядок строго
    ``call → parse → [deterministic repair → validate]``; при retryable-
    причине ПОСЛЕ ремонта — РОВНО одна исправляющая повторная попытка
    (second messages = system + исходный user + correction-блок с текстом
    причины; kill-switch'и hot-first: ``flags.summary_hybrid_l1_repair_enabled``
    / ``flags.summary_hybrid_l1_retry_enabled``). Транспорт
    (LLMError/LLMTimeoutError) и переполнение контракта (too_many_*) не
    ретраятся; L1-провал (после repair/retry) НЕ терминален — вызывающий
    контур уходит в LEVEL-2 fallback-пакет (§8/ADR-1027-10 D3/D4).
    """
    started = time.perf_counter()
    slot = resolve_l1_slot()
    source_rows = list(rows or [])
    chunk_count = 0
    if llm_call is None and llm is None:
        return error_result(REASON_INTERNAL_ERROR, duration_ms=0.0)

    # System-канон резолвится ДО упаковки: по формуле Q5 его токены вычитаются
    # из входного бюджета (маркер-оверхед учитывает сам pack_l1_input).
    system = system_prompt or resolve_prompt(
        PROMPT_PG_KEY, SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT)
    try:
        if budget:
            kind, limit = budget
        else:
            kind, raw_limit = resolve_l1_budget()
            limit = hybrid_input_budget(
                kind, raw_limit, system_text=system,
                output_reserve=hybrid_output_reserve_tokens(kind="l1"))
        token_limit = limit if kind == "tokens" else None
        char_limit = limit if kind == "chars" else None
        pack = pack_l1_input(source_rows, chat_id, token_limit=token_limit,
                             char_limit=char_limit)
        chunk_count = pack.chunk_count
        # ASAP-2.1 (T-3986, раздел 4 spec): L1_CONTEXT_PACK после pack_l1_input
        # (замещает FILTER_*; R17 — только числа/id; текстов нет).
        logger.info(
            "L1_CONTEXT_PACK | run_id=%s | chat_id=%s | source_messages=%d | "
            "packed_messages=%d | serialized_tokens=%d | physical_budget=%d | "
            "overflow=%d | skipped=%d | kind=%s",
            correlation_id or "none", chat_id, pack.source_count,
            len(pack.payload), pack.estimated_tokens, pack.limit,
            1 if pack.truncated else 0, len(pack.skipped_ids), pack.kind)
        if pack.truncated:
            # §93/§4.2: «не резать молча» — вытесненные бюджетом сообщения
            # видны WARN-логом (R17: только числа/id, без текстов).
            logger.warning(
                "L1 truncated input | run_id=%s | chat_id=%s | skipped=%d | "
                "kept=%d | chunks=%d | limit=%d (%s)",
                correlation_id or "none", chat_id, len(pack.skipped_ids),
                len(pack.payload), pack.chunk_count, pack.limit, pack.kind)
    except IdSpaceMismatch as exc:
        duration = (time.perf_counter() - started) * 1000.0
        _log_error(correlation_id=correlation_id, chat_id=chat_id,
                   model=slot.model, base_url=slot.base_url,
                   reason=REASON_ID_SPACE_MISMATCH,
                   error_type=type(exc).__name__, duration_ms=duration,
                   http_status=http_status_of(exc), attempts=attempts_of(exc))
        return invalid_result(REASON_ID_SPACE_MISMATCH, duration_ms=duration)
    except Exception as exc:  # pragma: no cover - защитная ветка
        duration = (time.perf_counter() - started) * 1000.0
        _log_error(correlation_id=correlation_id, chat_id=chat_id,
                   model=slot.model, base_url=slot.base_url,
                   reason=REASON_INTERNAL_ERROR, error_type=type(exc).__name__,
                   duration_ms=duration,
                   http_status=http_status_of(exc), attempts=attempts_of(exc))
        return error_result(REASON_INTERNAL_ERROR, duration_ms=duration)

    model = _effective_model(llm, slot) if llm is not None else slot.model
    base_url = _effective_base_url(llm, slot) if llm is not None else slot.base_url
    base_kwargs = dict(duration_ms=0.0, skipped_ids=pack.skipped_ids,
                       skipped_tg_ids=pack.skipped_tg_ids,
                       truncated=pack.truncated, chunk_count=pack.chunk_count)

    if not pack.payload:
        # Пустой вход: LLM не дёргаем (пустое не публикуется, §106).
        duration = (time.perf_counter() - started) * 1000.0
        result = empty_result(**dict(base_kwargs, duration_ms=duration))
        _log_complete(correlation_id=correlation_id, chat_id=chat_id,
                      result=result, model=model, base_url=base_url,
                      tokens_in=0, tokens_out=0, tokens_estimated=True,
                      chunk_count=chunk_count)
        return result

    _log_start(correlation_id=correlation_id, chat_id=chat_id,
               source_count=pack.source_count,
               estimated_tokens=pack.estimated_tokens,
               chunk_count=pack.chunk_count, model=model, base_url=base_url,
               dedicated=slot.dedicated)
    call = llm_call or _make_llm_call(llm, slot, correlation_id)
    user_content = build_l1_user_content(
        pack.payload, chunk_count=pack.chunk_count,
        chunk_starts=pack.chunk_starts)
    if focus_block:
        # S5/§80: focus «/summary про X» — как в legacy-пути (`_apply_focus`),
        # блок в НАЧАЛО user-контента; system-канон не тронут.
        user_content = focus_block + user_content
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    # ── ASAP-2 (контракт (b)/(c)/§15): call → parse → repair → validate →
    #    (ровно одна correction-повторная попытка, если причина всё ещё
    #    retryable ПОСЛЕ ремонта). Транспортные ошибки (LLMError/
    #    LLMTimeoutError) и переполнение контракта (too_many_*) — без ретрая.
    #    Kill-switch'и hot-first: flags.summary_hybrid_l1_repair_enabled /
    #    flags.summary_hybrid_l1_retry_enabled (env-слой — ClassVar'ы).
    repair_on = _repair_enabled()
    retry_enabled = _retry_enabled()
    max_attempts = 2 if retry_enabled else 1
    attempts = 1
    tokens_in = None
    tokens_out = None
    tokens_estimated = True
    result: L1Result | None = None
    base_kwargs.pop("duration_ms", None)
    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        try:
            raw_value = await call(messages)
            raw, usage = _normalise_call_result(raw_value)
            tokens_in, tokens_out = _extract_usage(usage)
            if tokens_in is None:
                tokens_in = pack.estimated_tokens
            if tokens_out is None:
                tokens_out = count_tokens(raw)
                tokens_estimated = True
            else:
                tokens_estimated = False
        except LLMError as exc:
            duration = (time.perf_counter() - started) * 1000.0
            reason = (REASON_LLM_TIMEOUT
                      if type(exc).__name__ == "LLMTimeoutError"
                      else REASON_LLM_ERROR)
            _log_error(correlation_id=correlation_id, chat_id=chat_id,
                       model=model, base_url=base_url, reason=reason,
                       error_type=type(exc).__name__, duration_ms=duration,
                       http_status=http_status_of(exc),
                       attempts=attempts_of(exc))
            return error_result(reason, duration_ms=duration, **base_kwargs)
        except Exception as exc:
            duration = (time.perf_counter() - started) * 1000.0
            _log_error(correlation_id=correlation_id, chat_id=chat_id,
                       model=model, base_url=base_url, reason=REASON_LLM_ERROR,
                       error_type=type(exc).__name__, duration_ms=duration,
                       http_status=http_status_of(exc),
                       attempts=attempts_of(exc))
            return error_result(REASON_LLM_ERROR, duration_ms=duration,
                                **base_kwargs)

        space: IdSpace = build_id_space(pack.payload)
        data, parse_reason = parse_l1_response(raw)
        duration = (time.perf_counter() - started) * 1000.0
        # §18 (контракт (k)): L1_PARSE — attempt/parse_status/raw_chars
        # (только числа/коды, R17).
        logger.info(
            "L1_PARSE | run_id=%s | chat_id=%s | attempt=%d | parse_status=%s"
            " | raw_chars=%d",
            correlation_id or "none", chat_id, attempt,
            (parse_reason if data is None else "ok"), len(raw or ""))
        useless_reason = ""
        # Unknown-id список собирается ВСЕГДА (в т.ч. repair OFF): он нужен
        # correction-блоку; в ЛОГИ не уходит никогда (R17 — только счётчики).
        unknown_ids = (_collect_unknown_ids(data, space)
                       if data is not None else [])
        if data is None:
            if parse_reason == REASON_OK:  # pragma: no cover - защитная ветка
                parse_reason = REASON_INTERNAL_ERROR
            result = invalid_result(parse_reason, duration_ms=duration,
                                    **base_kwargs)
        else:
            # repair МЕЖДУ parse и validate (kill-switch OFF → пропускается:
            # прежняя строгость валидатора v2 минус partition-правила).
            if repair_on:
                data, report = repair_l1(data, space)
                logger.info(
                    "L1_REPAIR | run_id=%s | chat_id=%s | attempt=%d | "
                    "overlapping_topic_memberships=%d | unknown_ids_removed=%d"
                    " | facts_removed=%d | topics_removed=%d | "
                    "evidence_membership_added=%d | "
                    "unassigned_conflicts_resolved=%d | topics_before=%d | "
                    "topics_after=%d | facts_before=%d | facts_after=%d | "
                    "useless=%d | useless_reason=%s",
                    correlation_id or "none", chat_id, attempt,
                    report.overlapping_topic_memberships,
                    report.unknown_ids_removed, report.facts_removed,
                    report.topics_removed, report.evidence_membership_added,
                    report.unassigned_conflicts_resolved,
                    report.topics_before, report.topics_after,
                    report.facts_before, report.facts_after,
                    1 if report.useless else 0,
                    report.useless_reason or "-")
                if report.useless:
                    useless_reason = report.useless_reason
                    result = invalid_result(REASON_L1_USELESS_AFTER_REPAIR,
                                            duration_ms=duration,
                                            **base_kwargs)
                else:
                    result = validate_l1_response(
                        data, space, duration_ms=duration,
                        skipped_ids=pack.skipped_ids,
                        skipped_tg_ids=pack.skipped_tg_ids,
                        truncated=pack.truncated,
                        chunk_count=pack.chunk_count)
                    if result.status == STATUS_OK and pack.truncated:
                        result = dataclasses.replace(
                            result, status=STATUS_TRUNCATED, truncated=True)
            else:
                # Kill-switch repair OFF → валидатор v2 без ремонта (прежняя
                # строгость минус partition-правила).
                result = validate_l1_response(
                    data, space, duration_ms=duration,
                    skipped_ids=pack.skipped_ids,
                    skipped_tg_ids=pack.skipped_tg_ids,
                    truncated=pack.truncated, chunk_count=pack.chunk_count)
                if result.status == STATUS_OK and pack.truncated:
                    result = dataclasses.replace(
                        result, status=STATUS_TRUNCATED, truncated=True)

        # Ровно одна исправляющая повторная попытка:retryable-причина ПОСЛЕ
        # repair+validate; вторая попытка = system + исходный user +
        # correction-блок (id-списки — только в промпт, в лог — код/числа).
        if (attempt < max_attempts and result.status == STATUS_INVALID
                and result.invalid_reason in _RETRYABLE_REASONS):
            logger.warning(
                "L1_CORRECTION_RETRY | run_id=%s | chat_id=%s | "
                "attempt=%d/%d | reason=%s",
                correlation_id or "none", chat_id, attempt, max_attempts,
                result.invalid_reason or "-")
            messages = _build_correction_messages(
                messages, result.invalid_reason or REASON_INVALID_JSON,
                unknown_ids=unknown_ids, useless_reason=useless_reason)
            continue
        break

    if result.status in (STATUS_INVALID,):
        logger.warning(
            "L1 invalid response | run_id=%s | chat_id=%s | reason=%s",
            correlation_id or "none", chat_id, result.invalid_reason or "-")

    _log_complete(correlation_id=correlation_id, chat_id=chat_id,
                  result=result, model=model, base_url=base_url,
                  tokens_in=tokens_in, tokens_out=tokens_out,
                  tokens_estimated=tokens_estimated, chunk_count=chunk_count,
                  attempts=attempts)
    return result
