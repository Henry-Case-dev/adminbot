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
# ── ASAP-3.1 (round 1028, ADR-1028-3 D3): Auto-бюджет + lossless chunking ──
from services import auto_budget as _auto_budget
from services import model_capacity as _model_capacity
from services.summary_budget_auto import (
    BUDGET_MODE_AUTO,
    BUDGET_MODE_LEGACY_STATIC,
    BUDGET_MODE_MANUAL_CAP,
    resolve_l1_effective_budget,
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
    _make_result,
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

    ASAP-3.1: live-путь run_l1 идёт через ``resolve_l1_effective_budget``
    (Auto/manual-cap/static); функция сохранена для совместимости/тестов.
    """
    return resolve_hybrid_context_budget(hot_get=hot_get,
                                         settings_obj=settings_obj)


# ── ASAP-3.1 (ADR-1028-3 D3, §118–§146): lossless chunking + coverage ──────

def summary_coverage_chunking_enabled() -> bool:
    """Kill-switch `SUMMARY_COVERAGE_CHUNKING_ENABLED` (env-only, default ON;
    резолв per-call; никогда не бросает). OFF → прежний single-pass pack
    (семантика «L1 truncated … skipped=…») байт-в-байт."""
    try:
        return bool(getattr(settings, "SUMMARY_COVERAGE_CHUNKING_ENABLED",
                            True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


# Coverage последнего прогона (process-local, §127/§135; R17 — числа/enum).
# НЕ вторая система usage — read-side витрина для Analytics/Summary UI (§24).
_LAST_RUN_COVERAGE: dict | None = None


def last_run_coverage() -> dict | None:
    """Снапшот покрытия последнего L1-прогона (или None)."""
    return dict(_LAST_RUN_COVERAGE) if _LAST_RUN_COVERAGE else None


def _record_run_coverage(*, source_total: int, processed: int, chunks: int,
                         unprocessed: int, budget_mode: str,
                         coverage_percent: float, window_start=None,
                         window_end=None, reason: str | None = None,
                         duplicate_overlap: int = 0) -> None:
    global _LAST_RUN_COVERAGE
    try:
        _LAST_RUN_COVERAGE = {
            "source_window_start": window_start,
            "source_window_end": window_end,
            "source_messages_total": int(source_total),
            "source_messages_processed": int(processed),
            "source_messages_unprocessed": int(unprocessed),
            "l1_chunks": int(chunks),
            # §127 (M-ASAP31-1 rework): фактическое число overlap-дубликатов
            # (сообщений, попавших в >1 chunk по reply-continuity).
            "duplicate_overlap_messages": int(duplicate_overlap),
            "coverage_percent": round(float(coverage_percent), 2),
            "budget_mode": str(budget_mode),
            "reason": reason,
        }
    except Exception:      # pragma: no cover - защитная ветка
        pass


def _emit_chunked(source_total: int, processed: int, chunks: int,
                  coverage_percent: float) -> None:
    try:
        from services.agentic_events import SUMMARY_L1_CHUNKED, \
            emit_agentic_event
        emit_agentic_event(
            SUMMARY_L1_CHUNKED, source_messages=int(source_total),
            processed_messages=int(processed), chunks=int(chunks),
            coverage=round(float(coverage_percent), 2))
    except Exception:      # fail-open
        pass


def _emit_coverage_degraded(source_total: int, processed: int,
                            unprocessed: int, chunks: int,
                            coverage_percent: float, reason: str) -> None:
    try:
        from services.agentic_events import SUMMARY_COVERAGE_DEGRADED, \
            emit_agentic_event
        emit_agentic_event(
            SUMMARY_COVERAGE_DEGRADED, source_messages=int(source_total),
            processed_messages=int(processed),
            unprocessed_messages=int(unprocessed), chunks=int(chunks),
            coverage=round(float(coverage_percent), 2), reason=str(reason))
    except Exception:      # fail-open
        pass
    logger.warning(
        "SUMMARY_COVERAGE_DEGRADED | source_messages=%d | processed=%d | "
        "unprocessed=%d | chunks=%d | coverage=%.2f | reason=%s",
        source_total, processed, unprocessed, chunks, coverage_percent,
        reason)


def merge_l1_payloads(payloads: list[dict]) -> dict:
    """Детерминированный merge §95-v2 payload'ов нескольких chunk-прогонов
    (§124/§126, без дополнительного LLM-вызова):

      * темы с пересечением ``message_ids`` (overlap-свидетельства) → одна
        связная тема (union message_ids, дедуп фактов по тексту + union
        evidence — stable-ID дедупликация §121);
      * темы без пересечений остаются раздельными (не «склеиваем» разное);
      * перенумерация ``thread_id``, ASC-порядок по первому сообщению;
      * ``unassigned_message_ids`` = union − упомянутые в темах.

    Никогда не бросает; пустой вход → ``{}``."""
    threads: list[dict] = []
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        for thread in payload.get("threads") or []:
            if isinstance(thread, dict) and thread.get("topic"):
                threads.append(thread)
    # ── Темы с пересечением ID → union (cross-chunk theme merge, §124) ──
    merged: list[dict] = []
    for thread in threads:
        ids = {mid for mid in (thread.get("message_ids") or [])
               if isinstance(mid, int)}
        target = None
        for candidate in merged:
            if ids & {mid for mid in candidate["message_ids"]}:
                target = candidate
                break
        if target is None:
            merged.append({
                "topic": str(thread.get("topic") or ""),
                "message_ids": list(ids),
                "facts": [dict(f) for f in (thread.get("facts") or [])],
            })
            continue
        target["message_ids"] = sorted(set(target["message_ids"]) | ids)
        existing_keys = {str(f.get("text") or "") for f in target["facts"]}
        for fact in thread.get("facts") or []:
            key = str(fact.get("text") or "")
            if key in existing_keys:
                for old in target["facts"]:
                    if str(old.get("text") or "") == key:
                        for eid in (fact.get("evidence_message_ids") or []):
                            if eid not in old["evidence_message_ids"]:
                                old["evidence_message_ids"].append(eid)
                        break
            else:
                target["facts"].append(dict(fact))
                existing_keys.add(key)
    if not merged:
        # Нет тем — объединяем только unassigned (все id в один payload).
        unassigned: list[int] = []
        for payload in payloads or []:
            if not isinstance(payload, dict):
                continue
            for mid in payload.get("unassigned_message_ids") or []:
                if isinstance(mid, int) and mid not in unassigned:
                    unassigned.append(mid)
        return {"schema_version": 2, "threads": [],
                "unassigned_message_ids": sorted(unassigned)}
    # ── Канонизация: сортировка ASC по числовому id, перенумерация ──
    for thread in merged:
        thread["message_ids"] = sorted(
            thread["message_ids"],
            key=lambda mid: (mid if isinstance(mid, int) else 0))
        thread["facts"] = [
            {"text": f.get("text"),
             "evidence_message_ids": sorted(
                 {eid for eid in (f.get("evidence_message_ids") or [])
                  if isinstance(eid, int)})}
            for f in thread["facts"] if f.get("text")]
    merged.sort(key=lambda t: (t["message_ids"][0] if t["message_ids"]
                               else 0))
    mentioned: set[int] = set()
    for thread in merged:
        mentioned.update(thread["message_ids"])
        for fact in thread["facts"]:
            mentioned.update(fact["evidence_message_ids"])
    unassigned: list[int] = []
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        for mid in payload.get("unassigned_message_ids") or []:
            if isinstance(mid, int) and mid not in mentioned \
                    and mid not in unassigned:
                unassigned.append(mid)
    threads_out = []
    for number, thread in enumerate(merged, start=1):
        threads_out.append({
            "thread_id": "T%d" % number,
            "topic": thread["topic"],
            "message_ids": thread["message_ids"],
            "facts": thread["facts"],
        })
    payload = {
        "schema_version": 2,
        "threads": threads_out,
        "unassigned_message_ids": sorted(unassigned),
    }
    # Служебные поля (response_mode/cover_prompt) — из первого payload'а,
    # где есть (изоляция L2-контента не меняется).
    for key in ("response_mode", "cover_prompt"):
        for raw in payloads or []:
            if isinstance(raw, dict) and raw.get(key):
                payload[key] = raw[key]
                break
    return payload


async def _run_l1_lossless(*, llm, rows: list, chat_id, correlation_id,
                           kind: str, limit: int, system_prompt: str,
                           llm_call, focus_block, budget_mode: str,
                           started: float, slot) -> L1Result:
    """Overflow-путь §120/§125: полный source set → lossless partition →
    L1 по каждому фрагменту → детерминированный merge → L2 (вызывает
    вызывающий контур). Каждый source ID ≥1 primary chunk (§121);
    overlap соседних фрагментов (1 сообщение, §121/§122 reply-continuity)
    дедуплицируется merge'ем по stable ID; oversized-одиночное сообщение →
    свой chunk (verbatim, без text[:N]; §123 — полное сообщение не режется).

    Партиционирование — по РЕАЛЬНОМУ serialized §92-размеру (тот же учёт,
    что в pack_l1_input), поэтому каждый chunk гарантированно помещается в
    бюджет и рекурсивный прогон НЕ эвоо-труncatится. Число LLM-вызовов
    определяется физикой (§125), НЕ искусственным бюджетом. Любой провал
    chunk-прогона → ``error_result`` (LEVEL-2 fallback-пакет строится
    вызывающим контуром из ПОЛНОГО набора — §140/§141 chronology-инвариант)."""
    source_rows = _sort_rows(list(rows or []))
    source_total = len(source_rows)
    # §127 (M-ASAP31-1 rework): окно прогона и overlap-дубликаты —
    # реальные значения (не заглушки).
    window_start = min((_row_ts(r) for r in source_rows), default=None)
    window_end = max((_row_ts(r) for r in source_rows), default=None)
    partitions, overlap_count = _partition_lossless(source_rows, chat_id,
                                                    limit, kind)
    if len(partitions) <= 1:
        # Не должен случиться (вызов только после truncated), но fail-open
        # к одному проходу без дробления (§125: happy path не дробится).
        return await run_l1(llm=llm, rows=rows, chat_id=chat_id,
                            correlation_id=correlation_id,
                            budget=(kind, limit),
                            system_prompt=system_prompt, llm_call=llm_call,
                            focus_block=focus_block, _allow_chunking=False)
    results: list[L1Result] = []
    processed_ids: set = set()
    for partition in partitions:
        result = await run_l1(
            llm=llm, rows=partition, chat_id=chat_id,
            correlation_id=correlation_id, budget=(kind, limit),
            system_prompt=system_prompt, llm_call=llm_call,
            focus_block=focus_block, _allow_chunking=False)
        results.append(result)
        if result.usable:
            for thread in (result.payload or {}).get("threads") or []:
                processed_ids.update(thread.get("message_ids") or [])
            processed_ids.update(
                (result.payload or {}).get("unassigned_message_ids") or [])
    usable_results = [r for r in results if r.usable]
    chunks_total = len(partitions)
    duration = (time.perf_counter() - started) * 1000.0
    if not usable_results:
        # §139: timeout ≠ drop; §140/§141: fallback — ПОЛНЫЙ source set
        # (LEVEL-2 у вызывающего). Явный degraded, не тихий успех.
        _record_run_coverage(
            source_total=source_total,
            processed=len(processed_ids),
            chunks=chunks_total,
            unprocessed=max(0, source_total - len(processed_ids)),
            budget_mode=budget_mode, coverage_percent=0.0,
            window_start=window_start, window_end=window_end,
            reason="chunk_run_failed",
            duplicate_overlap=overlap_count)
        _emit_coverage_degraded(
            source_total, len(processed_ids),
            max(0, source_total - len(processed_ids)), chunks_total, 0.0,
            "chunk_run_failed")
        first = results[0] if results else None
        reason = (first.invalid_reason if first is not None else None) \
            or REASON_LLM_ERROR
        return error_result(reason, duration_ms=duration)
    merged_payload = merge_l1_payloads(
        [r.payload for r in usable_results])
    unassigned_count = len(
        merged_payload.get("unassigned_message_ids") or [])
    threads_out = merged_payload.get("threads") or []
    facts_count = sum(len(t.get("facts") or []) for t in threads_out)
    merged = _make_result(
        STATUS_OK, payload=merged_payload, threads=len(threads_out),
        facts=facts_count, auto_unassigned=unassigned_count,
        duration_ms=duration, skipped_ids=(), skipped_tg_ids=(),
        truncated=False, chunk_count=chunks_total)
    coverage = 100.0 if source_total == 0 else \
        min(100.0, 100.0 * len(processed_ids) / max(1, source_total))
    _record_run_coverage(
        source_total=source_total, processed=len(processed_ids),
        chunks=chunks_total,
        unprocessed=max(0, source_total - len(processed_ids)),
        budget_mode=budget_mode, coverage_percent=coverage,
        window_start=window_start, window_end=window_end,
        reason=None if coverage >= 100.0 else "chunk_merge_partial",
        duplicate_overlap=overlap_count)
    # §128: успешный chunked-run = `SUMMARY_L1_CHUNKED`, НЕ «skipped».
    _emit_chunked(source_total, len(processed_ids), chunks_total, coverage)
    logger.info(
        "SUMMARY_L1_CHUNKED | run_id=%s | chat_id=%s | source_messages=%d | "
        "processed_messages=%d | chunks=%d | coverage=%.2f%% | "
        "budget_mode=%s",
        correlation_id or "none", chat_id, source_total,
        len(processed_ids), chunks_total, coverage, budget_mode)
    return merged


def _partition_lossless(rows: list, chat_id, limit: int, kind: str
                        ) -> tuple[list, int]:
    """Lossless-партиция полного source set по serialized §92-размеру
    (§120/§121). Хронологический ASC; каждое сообщение ≥1 primary chunk;
    overlap = 1 сообщение (reply-continuity §122, дедуп на merge);
    oversized-одиночное сообщение → свой chunk БЕЗ text[:N] (§123:
    «нельзя просто обрезать» — verbatim целиком; физически невлезающее
    одиночное сообщение ловится на стороне chunk-прогона как overflow).

    Возвращает ``(partitions, overlap_count)`` — §127 (M-ASAP31-1 rework):
    overlap_count = число сообщений, попавших в >1 chunk (дубликаты
    overlap'а, дедуплицируемые merge'ем по stable ID)."""
    partitions: list[list] = []
    current: list = []
    acc = 0
    overlap_count = 0
    for row in rows:
        try:
            size = _serialized_len(_payload_item(row, chat_id), kind)
        except Exception:      # pragma: no cover - защитная ветка
            size = limit + 1
        if current and acc + size > limit:
            # Закрыть партицию; overlap: последнее сообщение уходит в
            # следующую (reply-continuity, дедуп по stable ID на merge).
            overlap_row = current[-1]
            partitions.append(current)
            current = [overlap_row]
            overlap_count += 1
            try:
                acc = _serialized_len(_payload_item(overlap_row, chat_id),
                                      kind)
            except Exception:      # pragma: no cover
                acc = limit + 1
        current.append(row)
        acc += size
    if current:
        partitions.append(current)
    return partitions, overlap_count


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
                 focus_block=None, _allow_chunking: bool = True) -> L1Result:
    """Один прогон L1: §92-вход → §93-упаковка → LLM-вызов(ы) → §95-v2.

    ``llm`` — LLMClient (или совместимый мок); ``llm_call`` — инъекция канала
    (S5/тесты). ``budget`` — ``(kind, limit)``; ``None`` → ASAP-3.1
    Auto-семантика: capacity слота ``summary.l1`` через общий Auto Budget
    Resolver (``services/summary_budget_auto``; manual cap > 0 = размер
    ОДНОГО L1-запроса §137; kill-switch OFF → прежний static hybrid-путь
    байт-в-байт). ``focus_block`` — необязательный префикс
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

    ASAP-3.1 (ADR-1028-3 D3, §118–§146): при физическом переполнении и
    ``SUMMARY_COVERAGE_CHUNKING_ENABLED`` (default ON) — **lossless
    chunking** вместо eviction: полный source set нарезается на
    хронологические фрагменты, L1 по каждому, детерминированный merge
    (overlap дедуп по stable ID, темы через границу объединяются), coverage
    100%. ``_allow_chunking=False`` — внутренний рекурсивный прогон одного
    фрагмента (chunk-per-request). OFF флага → прежний single-pass pack
    (семантика «L1 truncated … skipped=…») байт-в-байт.
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
    budget_mode = "explicit" if budget else BUDGET_MODE_LEGACY_STATIC
    try:
        if budget:
            kind, limit = budget
        else:
            # ASAP-3.1 (T-4069): Auto/manual-cap/static — единая точка.
            kind, limit, budget_mode = await resolve_l1_effective_budget(
                system, slot)
        token_limit = limit if kind == "tokens" else None
        char_limit = limit if kind == "chars" else None
        pack = pack_l1_input(source_rows, chat_id, token_limit=token_limit,
                             char_limit=char_limit)
        chunk_count = pack.chunk_count
        # ── ASAP-3.1 §120/§128: переполнение → lossless chunking, НЕ drop.
        # Semantics «skipped=N из-за budget» как normal behavior не
        # существует: место «L1 truncated input» занимает chunked-статус.
        # OFF-паритет: legacy_static бюджет (kill-switch AUTO OFF) идёт по
        # прежнему single-pass пути байт-в-байт.
        if pack.truncated and _allow_chunking \
                and summary_coverage_chunking_enabled() \
                and budget_mode != BUDGET_MODE_LEGACY_STATIC:
            return await _run_l1_lossless(
                llm=llm, rows=source_rows, chat_id=chat_id,
                correlation_id=correlation_id, kind=kind, limit=limit,
                system_prompt=system, llm_call=llm_call,
                focus_block=focus_block, budget_mode=budget_mode,
                started=started, slot=slot)
        # ASAP-2.1 (T-3986, раздел 4 spec): L1_CONTEXT_PACK после pack_l1_input
        # (замещает FILTER_*; R17 — только числа/id; текстов нет).
        # ASAP-3.1: +budget_mode (auto/manual_cap/legacy_static, §78).
        logger.info(
            "L1_CONTEXT_PACK | run_id=%s | chat_id=%s | source_messages=%d | "
            "packed_messages=%d | serialized_tokens=%d | physical_budget=%d | "
            "overflow=%d | skipped=%d | kind=%s | budget_mode=%s",
            correlation_id or "none", chat_id, pack.source_count,
            len(pack.payload), pack.estimated_tokens, pack.limit,
            1 if pack.truncated else 0, len(pack.skipped_ids), pack.kind,
            budget_mode)
        if pack.truncated:
            # §93/§4.2: «не резать молча» — вытесненные бюджетом сообщения
            # видны WARN-логом (R17: только числа/id, без текстов).
            # ASAP-3.1: на ON-пути chunking сюда не доходим (см. выше) —
            # семантика «skipped» остаётся только на OFF-пути флага.
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

    # ── ASAP-3.1 §127/§128: coverage каждого прогона (single-pass path;
    # chunked-путь ведёт учёт в _run_l1_lossless) ───────────────────────────
    try:
        source_total = int(getattr(pack, "source_count", 0) or 0)
        packed = len(getattr(pack, "payload", ()) or ())
        unprocessed = len(getattr(pack, "skipped_ids", ()) or ())
        processed = max(0, source_total - unprocessed) if source_total \
            else packed
        coverage = 100.0 if source_total == 0 else \
            min(100.0, 100.0 * processed / max(1, source_total))
        chunks_single = int(getattr(pack, "chunk_count", 0) or 0) or 1
        # §127 (M-ASAP31-1 rework): окно прогона — реальные timestamps;
        # overlap в single-pass отсутствует (0).
        _run_window_start = min((_row_ts(r) for r in source_rows),
                                default=None)
        _run_window_end = max((_row_ts(r) for r in source_rows),
                              default=None)
        _record_run_coverage(
            source_total=source_total, processed=processed,
            chunks=chunks_single, unprocessed=unprocessed,
            budget_mode=budget_mode, coverage_percent=coverage,
            window_start=_run_window_start, window_end=_run_window_end,
            reason=None if unprocessed == 0 else "budget_truncation")
        if unprocessed > 0:
            # §127/§128: coverage<100% — явный degraded (OFF-путь chunking).
            _emit_coverage_degraded(
                source_total, processed, unprocessed, chunks_single,
                coverage, "budget_truncation")
        # §12: observed-слот для Analytics (числа прогона, R17-safe).
        _auto_budget.record_slot_observation(
            "summary.l1", int(tokens_in) if tokens_in is not None else packed)
    except Exception:      # fail-open: наблюдаемость не рвёт результат
        pass

    _log_complete(correlation_id=correlation_id, chat_id=chat_id,
                  result=result, model=model, base_url=base_url,
                  tokens_in=tokens_in, tokens_out=tokens_out,
                  tokens_estimated=tokens_estimated, chunk_count=chunk_count,
                  attempts=attempts)
    return result
