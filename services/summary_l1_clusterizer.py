"""S3 round1026 (ADR-1026-5 D1/D2/D4/D5) — L1 «Кластеризатор» (§92–§95).

**Автономный модуль S3** (в живой путь НЕ врезан — врезка S5/S6 по санкции):
вход §92 (``build_l1_payload`` из восстановленного контекста) → упаковка
§93-фрагментов в **один** вход → **ровно 1 LLM-вызов** L1 → парсер →
валидатор §95 (``summary_l1_contract``) → fail-closed ``L1Result``.

Инварианты (ADR-1026-5):
  * **ровно 1 вызов L1-слоя** (целевой пайплайн S5 = 2: L1+L2; третий вызов —
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
from services.summary_context_restore import build_l1_payload
from services.summary_filter import estimate_and_split
from services.summary_l1_contract import (
    REASON_ID_SPACE_MISMATCH,
    REASON_INTERNAL_ERROR,
    REASON_LLM_ERROR,
    REASON_LLM_TIMEOUT,
    REASON_OK,
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
from services.summary_prompts import SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT
from services.token_counter import count_tokens, resolve_chat_limit

logger = logging.getLogger(__name__)

MODULE = "summary"
STEP = "l1_clusterizer"
PROMPT_PG_KEY = "prompts.summary_l1_clusterizer_system_prompt"

# §5.6: бюджет — существующие ключи (`limits.summary_max_context_*`); дефолт
# токенов паритетен `_SUMMARY_CONTEXT_TOKEN_DEFAULT` summary_generator (30000).
L1_CONTEXT_TOKEN_DEFAULT = 30000
CHARS_ENV = "SUMMARY_MAX_CONTEXT_CHARS"

# Маркер границы §93-фрагмента в ЕДИНОМ входе L1 (не отдельный вызов).
CHUNK_MARKER_TEMPLATE = "=== ЧАСТЬ {index}/{total} ==="

# Оценка накладных расходов маркеров при упаковке (детерминированно).
_MARKER_OVERHEAD_TOKENS = count_tokens(CHUNK_MARKER_TEMPLATE.format(
    index=999, total=999))


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


def _unit(row, kind: str) -> int:
    text = _row_text(row)
    return count_tokens(text) if kind == "tokens" else len(text)


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
    объединяются в один вход (дедуп DB id, ASC, маркеры границ). Если итог
    всё равно не влезает в бюджет — детерминированно вытесняются САМЫЕ
    СТАРЫЕ сообщения (последнее сохраняется всегда), ``truncated=True`` +
    ``skipped_ids`` (§93 «не резать молча»). DB id → TG message_id — только
    через :func:`build_db_tg_map`.
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

    unit = lambda row: _unit(row, kind)  # noqa: E731 - локальный алиас
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
        truncated = True
        while len(used) > 1 and total > limit:
            removed = used.pop(0)
            total -= units.pop(0)
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
    """Бюджет входа L1 из существующих ключей ``limits.summary_max_context_*``.

    Токенный приоритет + аварийный chars-fallback — штатная семантика
    ``resolve_chat_limit`` (§5.6); per-chat-резолв — S5 при врезке.
    """
    if hot_get is None:
        from services import hot_config as hot
        hot_get = hot.get
    st = settings_obj or settings
    token_value = hot_get("limits.summary_max_context_tokens",
                          getattr(st, "SUMMARY_MAX_CONTEXT_TOKENS", None))
    chars_value = hot_get("limits.summary_max_context_chars",
                          getattr(st, "SUMMARY_MAX_CONTEXT_CHARS", 120000))
    return resolve_chat_limit(token_value, L1_CONTEXT_TOKEN_DEFAULT,
                              CHARS_ENV, int(chars_value or 0), "SUMMARY_L1")


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
                  chunk_count) -> None:
    logger.info(
        "L1_COMPLETE | run_id=%s | chat_id=%s | provider=%s | model=%s | "
        "tokens_in=%s | tokens_out=%s | tokens_estimated=%s | threads=%d | "
        "facts=%d | chunks=%d | auto_unassigned=%d | skipped=%d | "
        "truncated=%s | status=%s | invalid_reason=%s | duration_ms=%.0f",
        correlation_id or "none", chat_id, provider_host(base_url) or "-",
        model or "-", tokens_in if tokens_in is not None else "-",
        tokens_out if tokens_out is not None else "-", bool(tokens_estimated),
        result.threads_count, result.facts_count, chunk_count,
        result.auto_unassigned_count, len(result.skipped_ids),
        bool(result.truncated), result.status,
        result.invalid_reason or "-", result.duration_ms)


def _log_error(*, correlation_id, chat_id, model, base_url, reason, error_type,
               duration_ms) -> None:
    logger.warning(
        "L1_ERROR | run_id=%s | chat_id=%s | provider=%s | model=%s | "
        "error=%s | reason=%s | duration_ms=%.0f",
        correlation_id or "none", chat_id, provider_host(base_url) or "-",
        model or "-", error_type or "-", reason or "-", duration_ms)


# ── Ядро запуска L1 (без врезки в живой путь) ──────────────────────────────

async def run_l1(llm=None, rows=None, chat_id=None, *, correlation_id=None,
                 budget=None, system_prompt=None, llm_call=None,
                 focus_block=None) -> L1Result:
    """Один прогон L1: §92-вход → §93-упаковка → **1 LLM-вызов** → §95.

    ``llm`` — LLMClient (или совместимый мок); ``llm_call`` — инъекция канала
    (S5/тесты). ``budget`` — ``(kind, limit)``; ``None`` → существующие ключи
    ``limits.summary_max_context_*``. ``focus_block`` — необязательный префикс
    user-контента (S5/§80: focus «/summary про X» на ON-пути — как в legacy;
    ``None``/пусто → вход байт-в-байт прежний). Fail-closed: любое
    исключение/``LLMError`` → ``error``/``invalid`` с кодом причины,
    ``payload=None`` (в L2 не передаётся); ровно один физический вызов на
    запуск.
    """
    started = time.perf_counter()
    slot = resolve_l1_slot()
    source_rows = list(rows or [])
    chunk_count = 0
    tokens_estimated = True
    if llm_call is None and llm is None:
        return error_result(REASON_INTERNAL_ERROR, duration_ms=0.0)

    try:
        kind, limit = budget if budget else resolve_l1_budget()
        token_limit = limit if kind == "tokens" else None
        char_limit = limit if kind == "chars" else None
        pack = pack_l1_input(source_rows, chat_id, token_limit=token_limit,
                             char_limit=char_limit)
        chunk_count = pack.chunk_count
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
                   error_type=type(exc).__name__, duration_ms=duration)
        return invalid_result(REASON_ID_SPACE_MISMATCH, duration_ms=duration)
    except Exception as exc:  # pragma: no cover - защитная ветка
        duration = (time.perf_counter() - started) * 1000.0
        _log_error(correlation_id=correlation_id, chat_id=chat_id,
                   model=slot.model, base_url=slot.base_url,
                   reason=REASON_INTERNAL_ERROR, error_type=type(exc).__name__,
                   duration_ms=duration)
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
    system = system_prompt or resolve_prompt(PROMPT_PG_KEY,
                                             SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT)
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
                   error_type=type(exc).__name__, duration_ms=duration)
        return error_result(reason, duration_ms=duration, **{
            key: value for key, value in base_kwargs.items()
            if key != "duration_ms"})
    except Exception as exc:
        duration = (time.perf_counter() - started) * 1000.0
        _log_error(correlation_id=correlation_id, chat_id=chat_id,
                   model=model, base_url=base_url, reason=REASON_LLM_ERROR,
                   error_type=type(exc).__name__, duration_ms=duration)
        return error_result(REASON_LLM_ERROR, duration_ms=duration, **{
            key: value for key, value in base_kwargs.items()
            if key != "duration_ms"})

    data, parse_reason = parse_l1_response(raw)
    duration = (time.perf_counter() - started) * 1000.0
    if data is None:
        if parse_reason == REASON_OK:  # pragma: no cover - защитная ветка
            parse_reason = REASON_INTERNAL_ERROR
        result = invalid_result(parse_reason, duration_ms=duration,
                                **{key: value for key, value in
                                   base_kwargs.items()
                                   if key != "duration_ms"})
    else:
        space: IdSpace = build_id_space(pack.payload)
        result = validate_l1_response(
            data, space, duration_ms=duration, skipped_ids=pack.skipped_ids,
            skipped_tg_ids=pack.skipped_tg_ids, truncated=pack.truncated,
            chunk_count=pack.chunk_count)
        if result.status == STATUS_OK and pack.truncated:
            result = dataclasses.replace(
                result, status=STATUS_TRUNCATED, truncated=True)

    if result.status in (STATUS_INVALID,):
        logger.warning(
            "L1 invalid response | run_id=%s | chat_id=%s | reason=%s",
            correlation_id or "none", chat_id, result.invalid_reason or "-")

    _log_complete(correlation_id=correlation_id, chat_id=chat_id,
                  result=result, model=model, base_url=base_url,
                  tokens_in=tokens_in, tokens_out=tokens_out,
                  tokens_estimated=tokens_estimated, chunk_count=chunk_count)
    return result
