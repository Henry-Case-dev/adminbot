"""MCA-15 `mca-15-chat-statistics` (Wave 2, ADR-1028-12 D1/D2/D4/D6) — один
сервис измерения чата + детерминированный классификатор намерения.

Границы (spec §1–§3, sanctions §9):

* **Один сервис** — второй FTS-движок/text-to-SQL не создаётся; измерение
  исполняется поверх существующих репозиториев (`search_messages_fts*`) и
  существующего сборщика `build_fts_query` (аддитивные режимы).
* **Корпус один** — SQLite `smart_messages` (+FTS). PG сообщений чата не
  содержит; запрос «сумма хранилищ» → `unsupported` (без проверки пересечения
  counts не складываются).
* **Без durable-кеша** (Δ DDL = 0): каждое измерение — пересчёт; watermark
  `{max_id,max_timestamp}` из count-запроса, examples читаются с
  `id <= max_id` — число и примеры из одной версии данных.
* **Честные статусы** (D4): `ok|partial|unsupported|error`; `value=0, ok`
  только после успешного расчёта области; ошибка/таймаут → `value=null`;
  dedup/скан-кап → `partial` (+`stats_partial_corpus`); нет подтверждённой
  атрибуции → `unsupported`, не угадывание.
* **R17**: наружу — хэш спеки/метод/единица/область/числа/ID; сырой и
  нормализованный текст запроса в durable-канал не журналируется.
* Kill-switch K1 (`MCA_CHAT_STATISTICS_ENABLED`): OFF → сервис не вызывается
  потребителями, их поверхности = байт-в-байт 2.58.55.

`measure()` возвращает типизированный dict измерения; `MetricResult`/
`NumericClaim` (metric_id/human_label/verified_phrase, блоки C) строятся
поверх него без второго измерения.
"""
from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import logging
import re
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from services import mca_gates

logger = logging.getLogger(__name__)

# ── D1: metric / match_mode / policy enums ──────────────────────────────────
METRIC_MESSAGES = "messages"
METRIC_OCCURRENCES = "occurrences"
METRIC_DISTINCT_AUTHORS = "distinct_authors"
METRICS = frozenset({METRIC_MESSAGES, METRIC_OCCURRENCES,
                     METRIC_DISTINCT_AUTHORS})

MATCH_EXACT_PHRASE = "exact_phrase"
MATCH_TOKEN = "token"
MATCH_PREFIX = "prefix"
MATCH_ALL_TERMS = "all_terms"
MATCH_ANY_TERMS = "any_terms"
MATCH_MODES = frozenset({MATCH_EXACT_PHRASE, MATCH_TOKEN, MATCH_PREFIX,
                         MATCH_ALL_TERMS, MATCH_ANY_TERMS})

SOURCE_ANY = "any"
SOURCE_LIVE = "live"
SOURCE_IMPORT = "import"
SOURCE_KINDS = frozenset({SOURCE_ANY, SOURCE_LIVE, SOURCE_IMPORT})

SENDER_ANY = "any"
SENDER_HUMAN = "human"
SENDER_BOT = "bot"
SENDER_UNKNOWN = "unknown"
SENDER_KINDS = frozenset({SENDER_ANY, SENDER_HUMAN, SENDER_BOT,
                          SENDER_UNKNOWN})

QUOTE_INCLUDE = "include"
QUOTE_EXCLUDE = "exclude"
QUOTE_ONLY = "only"
QUOTE_FORWARD = frozenset({QUOTE_INCLUDE, QUOTE_EXCLUDE, QUOTE_ONLY})

NORMALIZATION_VERSION = "cs-norm-1"
CORPUS_SMART_MESSAGES = "smart_messages"
# Ярлык метода occurrences (spec §3.2): bounded keyset-скан, unicode61-токены.
OCCURRENCE_METHOD = "token_scan_unicode61_v1"
# Ярлык метода messages через FTS prefix-OR (широкий поиск, НЕ морфология).
FTS_PREFIX_OR_METHOD = "fts_prefix_or_messages_v1"
# Ярлык метода messages через точный режим матча (фраза/токен/AND/OR).
FTS_MATCH_METHOD = "fts_match_messages_v1"

STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_UNSUPPORTED = "unsupported"
STATUS_ERROR = "error"
STATUSES = frozenset({STATUS_OK, STATUS_PARTIAL, STATUS_UNSUPPORTED,
                      STATUS_ERROR})

COVERAGE_KNOWN_COMPLETE = "known_complete"
COVERAGE_PARTIAL = "partial"
COVERAGE_UNKNOWN = "unknown"

REASON_STATS_COUNT_ERROR = "stats_count_error"
REASON_STATS_PARTIAL_CORPUS = "stats_partial_corpus"
REASON_STATS_UNSUPPORTED = "stats_unsupported"
REASON_LORE_STATS_RECHECK_FLAGGED = "lore_stats_recheck_flagged"
# Числовые reason-коды блока C (единый словарь mca_events; D9).
REASON_NUMERIC_CLAIM_MISMATCH = "numeric_claim_mismatch"
REASON_NUMERIC_CLAIM_CORRECTED = "numeric_claim_corrected"
REASON_NUMERIC_CLAIM_FALLBACK = "numeric_claim_fallback"

# ── D6: intent ──────────────────────────────────────────────────────────────
INTENT_CHAT_STATISTICS = "chat_statistics"
INTENT_HISTORICAL_EVIDENCE = "historical_evidence"
INTENT_SOCIAL_BANTER = "social_banter"
INTENT_MIXED = "mixed"
INTENTS = frozenset({INTENT_CHAT_STATISTICS, INTENT_HISTORICAL_EVIDENCE,
                     INTENT_SOCIAL_BANTER, INTENT_MIXED})

REASON_CHAT_STATS_INTENT = "chat_stats_intent"
REASON_HISTORICAL_EVIDENCE_INTENT = "historical_evidence_intent"
REASON_SOCIAL_BANTER_INTENT = "social_banter_intent"

# ── токенизация (unicode61-совместимая: casefold + [а-яёa-z0-9]+) ───────────
_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+")

# Закрытые маркеры D6 (контекст и reply; НЕ слова «никогда»/«бот» сами по
# себе). Никакой жёсткой реплики на конкретный пример — только грамматика.
_COUNT_IMPERATIVE_RE = re.compile(
    r"\b(?:посчитай|посчитайте|подсчитай|подсчитайте|сосчитай|сосчитайте|"
    r"посчитать|подсчитать|сосчитать)\b")
_COUNT_HOWMANY_RE = re.compile(r"\bсколько\b")
_COUNT_OBJECT_RE = re.compile(
    r"(?:раз(?:а|ы|ов)?\b|сообщени|упомина|вхожден|статистик|"
    r"количеств|число\b|цифр|автор|участник)")
_HOWMANY_SPEECH_RE = re.compile(
    r"\bсколько\b.{0,80}(?:написал|написала|сказал|сказала|упомянул|"
    r"упомянула|говорил|говорила|писал|писала|называл|называла|отправил)")
_SEARCH_IMPERATIVE_RE = re.compile(
    r"\b(?:найди|найдите|найти|покажи|покажите|показать|вспомни|вспомните|"
    r"вспомнить|поищи|поищите|поискать|отыщи|отыскать|напомни|напомните)\b")
_WHEN_WHERE_RE = re.compile(r"\b(?:когда|где)\b")
_SPEECH_VERB_RE = re.compile(
    r"(?:называл|называла|говорил|говорила|писал|писала|упоминал|упоминала|"
    r"сказал|сказала|отвечал|отвечала)")
# Утверждение/подкол без просьбы проверить (banter): ассертивы о прошлом +
# эмоциональные маркеры. Сами слова «никогда»/«бот» — лишь часть окна.
_ASSERTION_MARKERS_RE = re.compile(
    r"(?:никогда|ни разу|не называл|не называла|не говорил|не говорила|"
    r"не писал|не писала|не объявлял|не объявляла|не упоминал|не упоминала|"
    r"всегда|вечно|опять|снова|как обычно|да ладно|конечно|врёшь|врешь)")
_EMOTION_MARKERS_RE = re.compile(
    r"(?:ахах|хаха|лол|ржу|смешно|бред|ого\b|вау|жесть|ну да|да ну)")
_FOLLOWUP_RE = re.compile(r"^\s*а\b")

# ── D6: короткий канон-хинт (прецедент format_nostalgia_hint) ───────────────
_STATS_HINT_TEXT = (
    "<Stats_Hint>\n"
    "Если просят число о чате — используй query_chat_memory со stats "
    "(явные metric и match_mode). В ответе называй только число/единицу/"
    "область из результата инструмента; не пересчитывай на глаз.\n"
    "</Stats_Hint>")


@dataclasses.dataclass(frozen=True)
class StatsIntent:
    """Результат детерминированного классификатора D6 (R17-safe)."""
    intent: str
    reason_code: str
    stats_hint: bool = False
    notable: bool = False


# ── D4 (T-4929): MetricResult / NumericClaim ────────────────────────────────
# Измерение привязано к запросу/версии/дате (metric_id из query_spec_hash +
# data_as_of), а не «вечный факт» о человеке: durable-кеша нет (Δ DDL=0),
# повторный запрос — пересчёт. Числа уходят наружу только через NumericClaim
# этого хода (per-turn, in-memory).

_UNIT_HUMAN_LABELS = {
    "messages": "сообщений с совпадением",
    "occurrences": "вхождений",
    "authors": "авторов",
}
_COVERAGE_HUMAN_LABELS = {
    COVERAGE_KNOWN_COMPLETE: "полнота: полная",
    COVERAGE_PARTIAL: "полнота: частичная (число неполное)",
    COVERAGE_UNKNOWN: "полнота: неизвестна",
}


@dataclasses.dataclass(frozen=True)
class NumericClaim:
    """Одно проверенное число хода (D4/§5.2): metric_id/unit/scope.

    Реестр — per-turn (`ToolContext.metric_results`); долговременного
    хранения числа нет. Число другого запроса/единицы не является
    подтверждением (A41)."""
    metric_id: str
    unit: str
    value: int
    scope_key: str = ""
    human_label: str = ""


@dataclasses.dataclass(frozen=True)
class MetricResult:
    """Типизированный контракт измерения (§5.1; T-4929).

    ``value=0,status=ok`` — только после успешного расчёта заданной области;
    timeout/ошибка → ``value=None``; partial-корпус не даёт «никогда»;
    unsupported → ``value=None`` + причина. ``metric_id`` =
    ``cs:<sha1-12 query_spec_hash>``. ``method``/``method_label``/
    ``author_counts`` — аддитивные поля для видимости метода и NumericClaim
    авторских разбивок (без второго измерения).
    """
    metric_id: str
    status: str
    value: int | None
    unit: str
    query_spec_hash: str
    human_label: str
    scope: dict
    coverage: str
    time_bounds: dict
    data_as_of: int
    watermark: dict
    author_ids: tuple = ()
    filters: dict = dataclasses.field(default_factory=dict)
    excluded_count: int = 0
    unknown_count: int = 0
    example_source_refs: tuple = ()
    duration_ms: int = 0
    reason: str | None = None
    error: str | None = None
    verified_phrase: str = ""
    metric: str = ""
    method: str = ""
    method_label: str = ""
    author_counts: tuple = ()


def metric_id_for(query_spec_hash_value: str) -> str:
    """`cs:<sha1-12>` от канонического хэша спеки (R17: наружу — ID)."""
    digest = hashlib.sha1(str(query_spec_hash_value or "").encode(
        "utf-8")).hexdigest()
    return f"cs:{digest[:12]}"


def _scope_human_suffix(result: dict, query: StatsQuery | None) -> str:
    """Человекочитаемая область (чат/период/авторы) без сырого текста."""
    parts: list[str] = []
    scope = result.get("scope") or {}
    chat_id = scope.get("chat_id")
    if chat_id is None and query is not None:
        chat_id = query.chat_id
    if chat_id is not None:
        parts.append(f"чат {chat_id}")
    bounds = result.get("time_bounds") or {}
    if bounds.get("first_date") or bounds.get("last_date"):
        parts.append("период {}–{}".format(bounds.get("first_date") or "?",
                                           bounds.get("last_date") or "?"))
    authors = scope.get("author_ids") or []
    if authors:
        parts.append("авторы: " + ",".join(str(a) for a in authors))
    return "; ".join(parts)


def human_label_for(result: dict, query: StatsQuery | None = None) -> str:
    """Детерминированный ярлык: единица + метод + область + полнота.

    Никакого сырого/нормализованного текста запроса (R17): только
    число/единица/метод/область/полнота."""
    status = str(result.get("status") or STATUS_UNSUPPORTED)
    value = result.get("value")
    if value is None or status not in (STATUS_OK, STATUS_PARTIAL):
        return f"измерение не выполнено (статус: {status})"
    unit = str(result.get("unit") or "")
    label = _UNIT_HUMAN_LABELS.get(unit, unit or "единиц")
    text = f"{label}: {int(value)}"
    if status == STATUS_PARTIAL:
        text += " (частично)"
    method = str(result.get("method_label") or result.get("method") or "")
    if method:
        text += f"; метод: {method}"
    suffix = _scope_human_suffix(result, query)
    if suffix:
        text += f"; {suffix}"
    coverage = str(result.get("coverage") or "")
    coverage_label = _COVERAGE_HUMAN_LABELS.get(coverage, "")
    if coverage_label:
        text += f"; {coverage_label}"
    return text


def build_metric_result(result: dict,
                        query: StatsQuery | None = None) -> MetricResult:
    """Обернуть типизированный dict измерения в MetricResult (T-4929).

    Второго измерения нет: принимает результат `measure()` либо
    типизированный `stats`-блок dig-контура. Отсутствующие поля — честные
    значения по умолчанию (None/пусто), не выдуманные."""
    data = dict(result or {})
    status = str(data.get("status") or STATUS_UNSUPPORTED)
    if status not in STATUSES:
        status = STATUS_ERROR
    raw_value = data.get("value")
    value = (int(raw_value)
             if isinstance(raw_value, (int, float))
             and not isinstance(raw_value, bool) else None)
    unit = str(data.get("unit") or (unit_for(query.metric) if query else "")
               or "")
    qhash = str(data.get("query_spec_hash")
                or (query_spec_hash(query) if query else ""))
    scope = dict(data.get("scope") or {})
    if query is not None and "chat_id" not in scope:
        scope["chat_id"] = int(query.chat_id)
    time_bounds = dict(data.get("time_bounds") or {})
    watermark = dict(data.get("watermark") or {})
    examples = list(data.get("examples") or [])
    refs = tuple(str(item.get("item_id")) for item in examples
                 if isinstance(item, dict) and item.get("item_id"))
    authors = tuple(dict(item) for item in (data.get("authors") or [])
                    if isinstance(item, dict))
    author_ids: tuple = ()
    if query is not None:
        author_ids = tuple(sorted(int(v) for v in (query.author_ids or ())))
    else:
        try:
            author_ids = tuple(sorted(
                int(v) for v in (scope.get("author_ids") or [])))
        except (TypeError, ValueError):
            author_ids = ()
    metric = str(data.get("metric") or (query.metric if query else "") or "")
    label = human_label_for(data, query)
    return MetricResult(
        metric_id=metric_id_for(qhash),
        status=status,
        value=value,
        unit=unit,
        query_spec_hash=qhash,
        human_label=label,
        scope=scope,
        coverage=str(data.get("coverage") or COVERAGE_UNKNOWN),
        time_bounds=time_bounds,
        data_as_of=int(data.get("data_as_of") or time.time()),
        watermark=watermark,
        author_ids=author_ids,
        filters={
            "source_kinds": scope.get("source_kinds"),
            "sender_kinds": scope.get("sender_kinds"),
            "quote_forward": scope.get("quote_forward"),
        },
        excluded_count=int(data.get("excluded_count") or 0),
        unknown_count=int(data.get("unknown_count") or 0),
        example_source_refs=refs,
        duration_ms=int(data.get("duration_ms") or 0),
        reason=(str(data.get("reason")) if data.get("reason") else None),
        error=(str(data.get("error")) if data.get("error") else None),
        verified_phrase=label if value is not None and status in (
            STATUS_OK, STATUS_PARTIAL) else "",
        metric=metric,
        method=str(data.get("method") or ""),
        method_label=str(data.get("method_label") or ""),
        author_counts=authors,
    )


def claim_for_result(result: MetricResult) -> NumericClaim | None:
    """Основной NumericClaim хода: только ok/partial с непустым значением."""
    if result.value is None or result.status not in (STATUS_OK, STATUS_PARTIAL):
        return None
    return NumericClaim(
        metric_id=result.metric_id, unit=result.unit, value=int(result.value),
        scope_key=f"chat:{result.scope.get('chat_id')}",
        human_label=result.human_label)


def claims_for_result(result: MetricResult) -> tuple[NumericClaim, ...]:
    """NumericClaim-мэппинг измерения: основное число + разбивка по авторам
    (аддитивно; числа авторов — сообщения по автору, не «авторы»)."""
    claims: list[NumericClaim] = []
    main = claim_for_result(result)
    if main is not None:
        claims.append(main)
    if result.status in (STATUS_OK, STATUS_PARTIAL) \
            and result.unit == "messages":
        for item in result.author_counts or ():
            try:
                count = int(item.get("count"))
            except (TypeError, ValueError):
                continue
            if count < 0:
                continue
            claims.append(NumericClaim(
                metric_id=result.metric_id, unit="messages", value=count,
                scope_key=f"author:{item.get('user_id')}"))
    return tuple(claims)


def metric_result_payload(result: dict,
                          query: StatsQuery | None = None, *,
                          metric_result: MetricResult | None = None) -> dict:
    """Типизированный JSON-блок stats-режима (§4.2): без голого числа."""
    mr = metric_result or build_metric_result(result, query)
    data = dict(result or {})
    return {
        "metric_id": mr.metric_id,
        "status": mr.status,
        "value": mr.value,
        "unit": mr.unit,
        "method": mr.method,
        "method_label": mr.method_label,
        "human_label": mr.human_label,
        "scope": dict(data.get("scope") or mr.scope),
        "coverage": mr.coverage,
        "time_bounds": dict(data.get("time_bounds") or {}),
        "data_as_of": mr.data_as_of,
        "watermark": dict(data.get("watermark") or {}),
        "excluded_count": mr.excluded_count,
        "unknown_count": mr.unknown_count,
        "examples": list(data.get("examples") or []),
        "verified_phrase": mr.verified_phrase,
        "reason": mr.reason,
    }


def build_measurement_diagnostic(
        result: MetricResult | dict, *, intent: str = "",
        include_sources: bool = True) -> dict:
    """R17-safe диагностический payload §24.5 (карточка/аналитика → измерение).

    Только коды/ID/числа/статусы: `query_spec_hash`, метод/единица, corpus/
    snapshot (watermark/data_as_of/coverage), статус счёта, NumericClaim
    mapping, ссылки на источники (канонические item-ID). Сырой и
    нормализованный текст запроса и SQL сюда не попадают никогда."""
    mr = (result if isinstance(result, MetricResult)
          else build_metric_result(result))
    claims = claims_for_result(mr)
    return {
        "intent": str(intent or ""),
        "metric_id": mr.metric_id,
        "query_spec_hash": mr.query_spec_hash,
        "normalization_version": NORMALIZATION_VERSION,
        "metric": mr.metric,
        "unit": mr.unit,
        "method": mr.method,
        "method_label": mr.method_label,
        "status": mr.status,
        "value": mr.value,
        "coverage": mr.coverage,
        "scope": dict(mr.scope),
        "watermark": dict(mr.watermark),
        "data_as_of": mr.data_as_of,
        "excluded_count": mr.excluded_count,
        "unknown_count": mr.unknown_count,
        "duration_ms": mr.duration_ms,
        "reason": mr.reason,
        "claims": [
            {"metric_id": c.metric_id, "unit": c.unit, "value": c.value,
             "scope_key": c.scope_key} for c in claims],
        "example_source_refs": (list(mr.example_source_refs)
                                if include_sources else []),
    }


def emit_measurement_event(result: MetricResult | dict, *, chat_id: int,
                           intent: str = "", component: str = "tool_router",
                           stage: str = "measurement") -> None:
    """Notable-событие измерения `chat_statistics` (R17-safe; fail-open).

    Статус виден отдельно (ok/partial/unsupported/error), ошибка счётчика ≠
    0; диагностический payload — в `source_ref_json` (без текста/SQL)."""
    try:
        from services import mca_events
        mr = (result if isinstance(result, MetricResult)
              else build_metric_result(result))
        outcome = {
            STATUS_OK: mca_events.OUTCOME_SUCCESS,
            STATUS_PARTIAL: mca_events.OUTCOME_SUCCESS,
            STATUS_UNSUPPORTED: mca_events.OUTCOME_SKIPPED,
            STATUS_ERROR: mca_events.OUTCOME_FAILED,
        }.get(mr.status, mca_events.OUTCOME_SKIPPED)
        fields = {
            "component": str(component),
            "stage": str(stage),
            "chat_id": int(chat_id),
            "status": mr.status,
            "duration_ms": int(mr.duration_ms),
            "source_ref_json": build_measurement_diagnostic(
                mr, intent=intent),
        }
        if mr.reason:
            fields["reason_code"] = mr.reason
        mca_events.emit_mca_event("chat_statistics", outcome=outcome,
                                  **fields)
    except Exception:      # fail-open: диагностика не рвёт поток
        logger.warning("[mca15_stats] measurement event failed")


@dataclasses.dataclass(frozen=True)
class StatsQuery:
    """D1: нормализованная спека измерения (frozen).

    ``text``/``terms`` — фраза и/или список; ``author_ids``/``subject_ids`` —
    канонические ID (автор ≠ субъект: subject без подтверждённой атрибуции →
    `unsupported`). ``interval_from``/``interval_to`` — unix-окно по
    `timestamp` в SQL до LIMIT. `timezone` — только для человекочитаемых дат.
    """
    chat_id: int
    metric: str = METRIC_MESSAGES
    match_mode: str = MATCH_TOKEN
    text: str = ""
    terms: tuple[str, ...] = ()
    author_ids: tuple[int, ...] = ()
    subject_ids: tuple[int, ...] = ()
    interval_from: int | None = None
    interval_to: int | None = None
    timezone: str = ""
    source_kinds: str = SOURCE_ANY
    sender_kinds: str = SENDER_ANY
    quote_forward: str = QUOTE_INCLUDE
    normalization_version: str = NORMALIZATION_VERSION
    corpus_scope: str = CORPUS_SMART_MESSAGES
    examples_limit: int | None = None


class _Unsupported(Exception):
    """Внутренний сигнал: спека не может быть измерена (не угадываем)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def normalize_terms(text: str) -> list[str]:
    """Нормализация пробелов/регистра/пунктуации: casefold-токены.

    Канон `cs-norm-1` (участвует в `query_spec_hash`); unicode61-совместимо.
    """
    return _TOKEN_RE.findall(str(text or "").casefold())


def resolve_terms(query: StatsQuery) -> list[str]:
    """Токены измерения по `match_mode` (валидация D1).

    `exact_phrase` требует text; `token` — ровно один токен; `prefix` — ≥1
    токен (явный префикс, НЕ морфология); `all_terms`/`any_terms` — ≥2 терма.
    """
    text_terms = normalize_terms(query.text)
    extra: list[str] = []
    for term in query.terms or ():
        extra.extend(normalize_terms(term))
    mode = query.match_mode
    if mode == MATCH_EXACT_PHRASE:
        if not text_terms:
            raise _Unsupported("exact_phrase_requires_text")
        return text_terms
    merged = list(dict.fromkeys(extra + text_terms))
    if mode == MATCH_TOKEN:
        if len(merged) != 1:
            raise _Unsupported("token_requires_single_term")
        return merged
    if mode == MATCH_PREFIX:
        if not merged:
            raise _Unsupported("prefix_requires_term")
        return merged
    if mode in (MATCH_ALL_TERMS, MATCH_ANY_TERMS):
        if len(merged) < 2:
            raise _Unsupported(f"{mode}_requires_two_terms")
        return merged
    raise _Unsupported("unknown_match_mode")


def _fts_mode(match_mode: str) -> str:
    """`match_mode` → режим единого сборщика `build_fts_query` (без второго)."""
    if match_mode == MATCH_EXACT_PHRASE:
        return "exact_phrase"
    if match_mode == MATCH_TOKEN:
        return "token"
    if match_mode == MATCH_PREFIX:
        return "prefix"
    if match_mode == MATCH_ALL_TERMS:
        return "all_terms"
    if match_mode == MATCH_ANY_TERMS:
        return "any_terms"
    raise _Unsupported("unknown_match_mode")


def method_label(match_mode: str) -> str:
    """Человекочитаемый ярлык метода (prefix явно НЕ морфология)."""
    if match_mode == MATCH_PREFIX:
        return "совпадение по префиксу (не морфологический анализ)"
    if match_mode == MATCH_EXACT_PHRASE:
        return "точная фраза (quoted FTS)"
    if match_mode == MATCH_TOKEN:
        return "точный токен"
    if match_mode == MATCH_ALL_TERMS:
        return "все термы (AND)"
    return "любой из термов (OR)"


def unit_for(metric: str) -> str | None:
    if metric == METRIC_MESSAGES:
        return "messages"
    if metric == METRIC_OCCURRENCES:
        return "occurrences"
    if metric == METRIC_DISTINCT_AUTHORS:
        return "authors"
    return None


def query_spec_hash(query: StatsQuery) -> str:
    """sha256 канонизированной JSON-спеки (наружу — только хэш, R17)."""
    try:
        terms = resolve_terms(query)
    except _Unsupported:
        terms = normalize_terms(query.text) + [
            t for term in (query.terms or ()) for t in normalize_terms(term)]
    spec = {
        "chat_id": int(query.chat_id),
        "metric": str(query.metric),
        "match_mode": str(query.match_mode),
        "terms": list(terms),
        "author_ids": sorted(int(v) for v in (query.author_ids or ())),
        "subject_ids": sorted(int(v) for v in (query.subject_ids or ())),
        "interval": [query.interval_from, query.interval_to],
        "timezone": str(query.timezone or ""),
        "source_kinds": str(query.source_kinds),
        "sender_kinds": str(query.sender_kinds),
        "quote_forward": str(query.quote_forward),
        "normalization_version": str(query.normalization_version),
        "corpus_scope": str(query.corpus_scope),
    }
    canonical = json.dumps(spec, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── D6: классификатор намерения (без LLM; контекст и reply) ─────────────────

def _has_count_request(text: str) -> bool:
    if _COUNT_IMPERATIVE_RE.search(text):
        return True
    if _COUNT_HOWMANY_RE.search(text) and (
            _COUNT_OBJECT_RE.search(text) or _HOWMANY_SPEECH_RE.search(text)):
        return True
    return bool(_COUNT_OBJECT_RE.search(text)
                and re.search(r"\bстатистик", text))


def _has_search_request(text: str) -> bool:
    if _SEARCH_IMPERATIVE_RE.search(text):
        return True
    return bool(_WHEN_WHERE_RE.search(text) and _SPEECH_VERB_RE.search(text))


def _has_banter_markers(text: str) -> bool:
    return bool(_ASSERTION_MARKERS_RE.search(text)
                or _EMOTION_MARKERS_RE.search(text))


def classify_stats_intent(text: str, *, reply_parent: str | None = None,
                          addressed: bool = True) -> StatsIntent:
    """D6: `chat_statistics`/`historical_evidence`/`social_banter`/`mixed`.

    Правила закрытые (контекст и reply; не только слова «никогда»/«бот»):

    * явная просьба измерить («сколько … раз/сообщений/упоминаний»,
      «посчитай», «статистика» + объект счёта) → `chat_statistics`;
    * «найди/покажи/вспомни, когда/где … называл/говорил» без маркеров
      счёта → `historical_evidence`;
    * просьба измерить + шутка/эмоция → `mixed` (две цели);
    * утверждение/подкол без просьбы проверить → `social_banter`
      (stats-хинта нет — подкол не получает обязательный отчёт);
    * короткий follow-up «а …» на ответ со счётом (reply-контекст) →
      `chat_statistics`.

    `stats_hint` выдаётся только для `chat_statistics`/`mixed` и только
    адресованных сообщений; `notable` — были ли явные маркеры (для
    notable-only событий; per-reply «успехов» нет). Инструменты глобально
    НЕ блокируются; жёсткой реплики на конкретный пример нет.
    """
    source = str(text or "").casefold()
    parent = str(reply_parent or "").casefold()
    count = _has_count_request(source)
    search = _has_search_request(source)
    banter = _has_banter_markers(source)
    if count and banter:
        intent, reason = INTENT_MIXED, REASON_CHAT_STATS_INTENT
    elif count:
        intent, reason = INTENT_CHAT_STATISTICS, REASON_CHAT_STATS_INTENT
    elif search:
        intent, reason = (INTENT_HISTORICAL_EVIDENCE,
                          REASON_HISTORICAL_EVIDENCE_INTENT)
    elif (addressed and parent
          and (_has_count_request(parent)
               or bool(_COUNT_OBJECT_RE.search(parent)))
          and _FOLLOWUP_RE.search(source) and len(source) <= 60):
        intent, reason = INTENT_CHAT_STATISTICS, REASON_CHAT_STATS_INTENT
    else:
        intent, reason = INTENT_SOCIAL_BANTER, REASON_SOCIAL_BANTER_INTENT
    hint = intent in (INTENT_CHAT_STATISTICS, INTENT_MIXED) and bool(addressed)
    return StatsIntent(intent=intent, reason_code=reason, stats_hint=hint,
                       notable=bool(count or search or banter))


def stats_hint_block() -> str:
    """Короткий канон-хинт D6 (для существующей сборки payload)."""
    return _STATS_HINT_TEXT


async def collect_candidates(db, memory, *, chat_id: int, query: str,
                             top_k: int = 8,
                             mode: str = "history", time_from=None,
                             time_to=None,
                             participants=(), reply_depth: int = 6):
    """Примеры/кандидаты исторического поиска — ТОЛЬКО через `retrieve()`
    (mca-07, L-MCA07-5): второй комбинированный retrieval запрещён.

    Не участвует в count-пути и не меняет условие измерения. Возвращает
    `RetrievalResult` (никогда не бросает — контракт mca-07)."""
    from services.mca_retrieval_context import RetrievalRequest, retrieve
    request = RetrievalRequest(
        chat_id=int(chat_id), query=str(query or ""), mode=str(mode or "auto"),
        top_k=max(1, int(top_k)), time_from=time_from, time_to=time_to,
        participants=tuple(int(v) for v in (participants or ())
                           if v is not None),
        reply_depth=max(0, int(reply_depth)))
    return await retrieve(db, memory, request)


# ── D1/D2/D4: измерение ─────────────────────────────────────────────────────

def _format_date(ts, tz_name: str = "") -> str:
    """unix ts → YYYY-MM-DD в tz чата (пусто при отсутствии)."""
    if not ts:
        return ""
    try:
        seconds = int(ts)
    except (TypeError, ValueError):
        return ""
    if not seconds:
        return ""
    try:
        from services.canonical_context import resolve_timezone
        resolved = resolve_timezone(str(tz_name or ""), fallback="UTC")
        moment = datetime.datetime.fromtimestamp(
            seconds, datetime.timezone.utc).astimezone(ZoneInfo(resolved))
    except (ValueError, OSError, OverflowError, ZoneInfoNotFoundError):
        return ""
    return moment.strftime("%Y-%m-%d")


def _count_occurrences(text: str, terms: list[str], match_mode: str) -> int:
    """Вхождения по методу `token_scan_unicode61_v1` (bounded-скан)."""
    tokens = _TOKEN_RE.findall(str(text or "").casefold())
    if match_mode == MATCH_EXACT_PHRASE:
        size = len(terms)
        if not size:
            return 0
        return sum(1 for i in range(len(tokens) - size + 1)
                   if tokens[i:i + size] == terms)
    if match_mode == MATCH_TOKEN:
        return sum(1 for token in tokens if token == terms[0])
    if match_mode == MATCH_PREFIX:
        return sum(1 for token in tokens
                   if any(token.startswith(term) for term in terms))
    wanted = set(terms)
    return sum(1 for token in tokens if token in wanted)


def _base_result(query: StatsQuery) -> dict:
    return {
        "status": STATUS_UNSUPPORTED,
        "value": None,
        "unit": unit_for(query.metric),
        "metric": str(query.metric),
        "method": "",
        "method_label": "",
        "query_spec_hash": query_spec_hash(query),
        "scope": {
            "chat_id": int(query.chat_id),
            "corpus": str(query.corpus_scope),
            "interval_from": query.interval_from,
            "interval_to": query.interval_to,
            "timezone": str(query.timezone or ""),
            "author_ids": sorted(int(v) for v in (query.author_ids or ())),
            "source_kinds": str(query.source_kinds),
            "sender_kinds": str(query.sender_kinds),
            "quote_forward": str(query.quote_forward),
        },
        "coverage": COVERAGE_UNKNOWN,
        "time_bounds": {"first_seen": None, "last_seen": None,
                        "first_date": "", "last_date": ""},
        "watermark": {"max_id": None, "max_timestamp": None},
        "data_as_of": int(time.time()),
        "excluded_count": 0,
        "unknown_count": 0,
        "sender_unknown_count": 0,
        "examples": [],
        "authors": [],
        "reason": None,
        "normalization_version": str(query.normalization_version),
        "corpus_scope": str(query.corpus_scope),
        "duration_ms": 0,
    }


def _validate(query: StatsQuery) -> None:
    """Спека не измеряема → `_Unsupported` (никогда не угадываем)."""
    if query.metric not in METRICS:
        raise _Unsupported("unknown_metric")
    if query.match_mode not in MATCH_MODES:
        raise _Unsupported("unknown_match_mode")
    if str(query.normalization_version or "") != NORMALIZATION_VERSION:
        raise _Unsupported("normalization_version_unsupported")
    if str(query.corpus_scope or "") != CORPUS_SMART_MESSAGES:
        # Сумма хранилищ без проверки пересечения запрещена (D1/§3.4).
        raise _Unsupported("corpus_sum_unsupported")
    if str(query.source_kinds or SOURCE_ANY) not in SOURCE_KINDS:
        raise _Unsupported("unknown_source_kind")
    if str(query.quote_forward or QUOTE_INCLUDE) not in QUOTE_FORWARD:
        raise _Unsupported("unknown_quote_forward")
    sender = str(query.sender_kinds or SENDER_ANY)
    if sender not in SENDER_KINDS:
        raise _Unsupported("unknown_sender_kind")
    if sender in (SENDER_HUMAN, SENDER_BOT):
        # Надёжного поля «бот» в корпусе нет — не угадываем (D1).
        raise _Unsupported("sender_kind_unavailable")
    if query.subject_ids:
        # Субъект без подтверждённой атрибуции (mca-22/provenance) — не
        # приписываем: subject ≠ author.
        raise _Unsupported("subject_attribution_unconfirmed")


async def measure(db, query: StatsQuery) -> dict:
    """Типизированное измерение по одной нормализованной спеке (D1).

    count и examples строятся из ОДНОЙ спеки; все фильтры действуют в SQL
    ДО LIMIT; examples читаются с `id <= watermark.max_id`. Ошибка → статус
    `error`/`value=null` (не ноль); dedup/скан-кап → `partial`; неспека →
    `unsupported`. Никогда не бросает."""
    started = time.monotonic()
    result = _base_result(query)
    try:
        _validate(query)
        terms = resolve_terms(query)
        if str(query.quote_forward or QUOTE_INCLUDE) != QUOTE_INCLUDE:
            # Нет колонок метаданных quote/forward → не угадываем точный
            # очищенный результат (spec §3.1): честный unsupported.
            try:
                cols = await db._smart_messages_columns()
            except Exception:
                cols = set()
            if cols and not {"is_forward", "forward_source",
                             "quote_text"} <= cols:
                raise _Unsupported("quote_metadata_missing")
        from services.summary_memory import build_fts_query
        match = build_fts_query(terms, mode=_fts_mode(query.match_mode))
        if not match:
            raise _Unsupported("empty_terms")
    except _Unsupported as exc:
        result.update({"status": STATUS_UNSUPPORTED, "value": None,
                       "reason": REASON_STATS_UNSUPPORTED})
        result["scope"]["unsupported_detail"] = exc.detail
        result["duration_ms"] = int((time.monotonic() - started) * 1000)
        return result
    except Exception as exc:      # pragma: no cover - defensive
        logger.warning("[mca15_stats] spec build failed | error=%s",
                       type(exc).__name__)
        result.update({"status": STATUS_ERROR, "value": None,
                       "reason": REASON_STATS_COUNT_ERROR})
        result["duration_ms"] = int((time.monotonic() - started) * 1000)
        return result

    result["method"] = (FTS_PREFIX_OR_METHOD if query.match_mode == MATCH_PREFIX
                        else FTS_MATCH_METHOD)
    if query.metric == METRIC_OCCURRENCES:
        result["method"] = OCCURRENCE_METHOD
    result["method_label"] = method_label(query.match_mode)

    examples_limit = mca_gates.chat_stats_examples_max()
    if query.examples_limit is not None:
        try:
            examples_limit = max(1, min(examples_limit,
                                        int(query.examples_limit)))
        except (TypeError, ValueError):
            pass
    max_rows = mca_gates.chat_stats_occurrence_max_rows()

    try:
        excluded_duplicates = await db.count_duplicate_identity_rows(
            chat_id=query.chat_id)
        stats = await db.search_messages_fts_count_by_author(
            query.chat_id, match,
            since_ts=int(query.interval_from or 0),
            until_ts=int(query.interval_to or 0),
            author_ids=query.author_ids,
            source_kind=str(query.source_kinds or SOURCE_ANY),
            quote_forward=str(query.quote_forward or QUOTE_INCLUDE))
        count = int(stats.get("count") or 0)
        max_id = stats.get("max_id")
        unknown_count = int(stats.get("unknown_count") or 0)
        first_seen = stats.get("first_seen")
        last_seen = stats.get("last_seen")
        # T-4924: ключ автора — канонический user_id (имя — подпись); смена
        # алиаса не дробит ID, два одинаковых имени не сливаются. Строки без
        # user_id — в unknown_count, не приписываются.
        authors_by_id: dict[int, dict] = {}
        for entry in (stats.get("by_author") or []):
            uid = entry.get("user_id")
            if uid is None:
                continue
            key = int(uid)
            item = authors_by_id.get(key)
            if item is None:
                authors_by_id[key] = {
                    "user_id": key,
                    "label": str(entry.get("author_name") or ""),
                    "count": int(entry.get("count") or 0)}
            else:
                item["count"] += int(entry.get("count") or 0)
                if not item["label"]:
                    item["label"] = str(entry.get("author_name") or "")
        authors = sorted(authors_by_id.values(),
                         key=lambda a: (-a["count"], str(a["label"]),
                                        a["user_id"]))
        distinct_ids = set(authors_by_id)

        coverage = COVERAGE_KNOWN_COMPLETE
        partial_reasons: list[str] = []
        if excluded_duplicates:
            coverage = COVERAGE_PARTIAL
            partial_reasons.append(REASON_STATS_PARTIAL_CORPUS)

        sender = str(query.sender_kinds or SENDER_ANY)
        sender_unknown = count if sender in (SENDER_ANY, SENDER_UNKNOWN) else 0

        if query.metric == METRIC_MESSAGES:
            value = count
        elif query.metric == METRIC_DISTINCT_AUTHORS:
            value = len(distinct_ids)
            if unknown_count:
                coverage = COVERAGE_PARTIAL
                partial_reasons.append(REASON_STATS_PARTIAL_CORPUS)
        else:  # occurrences — bounded keyset-скан
            if count > max_rows:
                value = None
                coverage = COVERAGE_PARTIAL
                partial_reasons.append(REASON_STATS_PARTIAL_CORPUS)
            else:
                value = await _scan_occurrences(
                    db, query, match, terms, max_id=max_id)
    except Exception as exc:
        logger.warning("[mca15_stats] measure failed | metric=%s | error=%s",
                       query.metric, type(exc).__name__)
        result.update({"status": STATUS_ERROR, "value": None,
                       "coverage": COVERAGE_UNKNOWN,
                       "reason": REASON_STATS_COUNT_ERROR,
                       "duration_ms": int((time.monotonic() - started) * 1000)})
        return result

    # examples — из той же спеки, с watermark-границей (одна версия данных).
    examples: list[dict] = []
    try:
        from services.canonical_context import resolve_item_id
        rows = await db.search_messages_fts(
            query.chat_id, match, examples_limit,
            since_ts=int(query.interval_from or 0),
            until_ts=int(query.interval_to or 0),
            author_ids=query.author_ids,
            source_kind=str(query.source_kinds or SOURCE_ANY),
            quote_forward=str(query.quote_forward or QUOTE_INCLUDE),
            max_id=max_id)
        for row in rows or []:
            item = dict(row)
            text = str(item.get("text") or "").strip()
            examples.append({
                "item_id": resolve_item_id(
                    tg_message_id=item.get("tg_message_id"),
                    message_id=item.get("id")),
                "author_id": item.get("user_id"),
                "author_label": str(item.get("author_name") or ""),
                "timestamp": item.get("timestamp"),
                "text": text[:200],
            })
    except Exception as exc:
        logger.warning("[mca15_stats] examples failed | error=%s",
                       type(exc).__name__)
        coverage = COVERAGE_PARTIAL
        partial_reasons.append(REASON_STATS_PARTIAL_CORPUS)

    status = STATUS_OK
    reason = None
    if coverage == COVERAGE_PARTIAL and partial_reasons:
        status = STATUS_PARTIAL
        reason = REASON_STATS_PARTIAL_CORPUS
    if query.metric == METRIC_OCCURRENCES and value is None:
        # Скан-кап: частичное число за полное не выдаём (spec §3.2).
        status = STATUS_PARTIAL
        reason = REASON_STATS_PARTIAL_CORPUS
    result.update({
        "status": status,
        "value": value,
        "coverage": coverage,
        "time_bounds": {
            "first_seen": first_seen,
            "last_seen": last_seen,
            "first_date": _format_date(first_seen, query.timezone),
            "last_date": _format_date(last_seen, query.timezone),
        },
        "watermark": {"max_id": max_id, "max_timestamp": last_seen},
        "excluded_count": int(excluded_duplicates or 0),
        "unknown_count": unknown_count,
        "sender_unknown_count": sender_unknown,
        "examples": examples,
        "authors": authors,
        "reason": reason,
        "duration_ms": int((time.monotonic() - started) * 1000),
    })
    return result


async def _scan_occurrences(db, query: StatsQuery, match: str,
                            terms: list[str], *, max_id) -> int:
    """Bounded keyset-скан совпавших строк порциями (read-only, без job-очередей)."""
    total = 0
    after_id = 0
    page = 500
    while True:
        rows = await db.search_messages_fts(
            query.chat_id, match, page,
            since_ts=int(query.interval_from or 0),
            until_ts=int(query.interval_to or 0),
            author_ids=query.author_ids,
            source_kind=str(query.source_kinds or SOURCE_ANY),
            quote_forward=str(query.quote_forward or QUOTE_INCLUDE),
            max_id=max_id, after_id=after_id)
        if not rows:
            break
        last = after_id
        for row in rows:
            item = dict(row)
            total += _count_occurrences(item.get("text"), terms,
                                        query.match_mode)
            last = max(last, int(item.get("id") or 0))
        if len(rows) < page or last <= after_id:
            break
        after_id = last
    return total
