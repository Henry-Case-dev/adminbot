"""S7 round1026 (ADR-1026-9 D1/D2/D6) — сквозной ``run_id`` и события §108/§109.

Единая точка форматирования логов **жизненного цикла** Саммари
(``SUMMARY_START``/``SUMMARY_COMPLETE``/``SUMMARY_FAILED``) и общий
R17-safe набор полей ошибки §109. `run_id` = существующий
``correlation_id`` (``usage_events.new_correlation_id()``, UUID4 hex);
**второй идентификатор не вводится** (D1). Одна точка создания на прогон —
живой путь ``summary_generator._run`` и dry-run ``summary_test_run``;
этапные события получают его параметром.

Инварианты (ADR-1026-9 D6/D7):
  * **R17**: только числа/коды/id/host/HTTP-статус/тип ошибки/причина/попытки;
    без секретов, промптов, сырых текстов сообщений и ответов LLM
    (маскировка — существующий ``log_ring.sanitize``);
  * **best-effort**: любая ошибка самого логирования не прерывает и не
    искажает пайплайн (fail-open);
  * **Δ DDL=0**: события идут в существующий ring-buffer + файловые логи;
  * ``provider`` — **host** (без схемы/пути/query/ключа), а не полный URL.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# HTTP-статус из текста исключения (форматы llm_client: «HTTP 403»,
# «server error 502», «auth failed (401)», «status=429»…). R17-safe.
_HTTP_STATUS_RE = re.compile(
    r"\b(?:HTTP\s+|server error |auth failed \(|status=|rate limited \()(\d{3})\b")

# Число попыток из текста исключения (форматы llm_client: «…after 3 attempts»,
# «…attempts=3»). B-R1026S7-2: реальные исключения атрибут не выставляют —
# число есть только в тексте; в лог уходит только само число (R17-safe).
_ATTEMPTS_RE = re.compile(
    r"\bafter (\d+) attempts?\b|\battempts[=:]\s*(\d+)\b", re.IGNORECASE)

# Допустимые значения статусов (D2).
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_DEGRADED = "degraded"
STATUS_FAILED = "failed"

# Причина обрезается — в лог не должен попасть длинный текст (R17).
_REASON_MAX = 200


def provider_host(base_url: str) -> str:
    """R17-safe провайдер: только host (без пути/ключа/query)."""
    try:
        return urlsplit(str(base_url or "")).hostname or ""
    except Exception:  # pragma: no cover - защитная ветка
        return ""


def http_status_of(exc: BaseException) -> int | None:
    """HTTP-статус причины из атрибута исключения либо его текста."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and 100 <= status < 1000:
        return status
    try:
        match = _HTTP_STATUS_RE.search(str(exc))
    except Exception:  # pragma: no cover - защитная ветка
        return None
    return int(match.group(1)) if match else None


def attempts_of(exc: BaseException) -> int | None:
    """Число попыток из текста исключения либо его атрибута.

    B-R1026S7-2: реальные ``llm_client``-исключения (``LLMRateLimitError``,
    ``LLMServerError``, ``LLMTimeoutError``) не выставляют ``attempts`` —
    число есть только в тексте («…after 3 attempts…»). Порядок разбора:
    текст → атрибут → ``None``; в лог попадает только число (R17).
    """
    try:
        match = _ATTEMPTS_RE.search(str(exc))
    except Exception:  # pragma: no cover - защитная ветка
        match = None
    if match:
        raw = match.group(1) or match.group(2)
        try:
            return int(raw)
        except (TypeError, ValueError):  # pragma: no cover - защитная ветка
            pass
    value = getattr(exc, "attempts", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_reason(value) -> str:
    """Короткая R17-safe причина: код/тип без сырого текста."""
    text = str(value or "").strip()
    if not text:
        return ""
    # Первая строка, обрезка по длине — на случай многострочного сообщения.
    return text.splitlines()[0][:_REASON_MAX]


def _num(value) -> str:
    return str(value) if value is not None else "-"


@dataclass
class RunContext:
    """In-memory контекст прогона для §110-раскрытия/§112 (D3, без таблицы).

    Заполняется этапами по мере прохождения; ``status`` переводится в
    ``failed`` через :meth:`fail`/`fail_from_exc` (тогда ``_run`` эмитит
    ``SUMMARY_FAILED`` вместо ``SUMMARY_COMPLETE``).
    """

    run_id: str
    chat_id: int
    mode: str = "off"                 # off | hybrid_l2
    manual: bool = False
    has_trigger: bool = False
    source_count: int | None = None
    saved_count: int | None = None
    restored_count: int | None = None
    threads: int | None = None
    paragraphs: int | None = None
    cover_status: str | None = None   # ok | unavailable | none
    # S8 (ADR-1026-10 D2): аддитивные поля снапшота прогона для карты вызовов
    # (§112/§111) — filter-метрики S1 и состояние серверного форматирования.
    # Заполняются этапами; в лог §108 НЕ выводятся (R17-поверхность не растёт).
    drop_percent: float | None = None
    filter_status: str | None = None
    filter_duration_ms: float | None = None
    format_channel: str | None = None
    format_status: str | None = None
    format_duration_ms: float | None = None
    status: str = STATUS_OK
    stage: str | None = None
    model: str | None = None
    provider: str | None = None
    http_status: int | None = None
    error_type: str | None = None
    reason: str | None = None
    attempts: int | None = None
    started: float = field(default_factory=time.perf_counter)

    def duration_ms(self) -> float:
        try:
            return (time.perf_counter() - self.started) * 1000.0
        except Exception:  # pragma: no cover - защитная ветка
            return 0.0

    def fail(self, *, stage: str, reason=None, model=None, provider=None,
             http_status=None, error_type=None, attempts=None) -> None:
        """Пометить прогон как провалившийся (§109-поля, R17-safe)."""
        self.status = STATUS_FAILED
        self.stage = stage or self.stage
        if reason is not None:
            self.reason = _safe_reason(reason)
        if model is not None:
            self.model = model
        if provider is not None:
            self.provider = provider
        if http_status is not None:
            self.http_status = http_status
        if error_type is not None:
            self.error_type = error_type
        if attempts is not None:
            self.attempts = attempts

    def fail_from_exc(self, *, stage: str, exc: BaseException) -> None:
        """§109-поля из исключения (без сырого текста: тип/код/host)."""
        reason = getattr(exc, "reason", None)
        self.fail(
            stage=stage,
            reason=reason if reason else type(exc).__name__,
            error_type=type(exc).__name__,
            http_status=http_status_of(exc),
            attempts=attempts_of(exc),
        )


# ── §108: жизненный цикл (R17-safe, best-effort) ───────────────────────────

def log_summary_start(ctx: RunContext) -> None:
    try:
        logger.info(
            "SUMMARY_START | run_id=%s | chat_id=%s | mode=%s | manual=%s | "
            "source_count=%s | has_trigger=%s",
            ctx.run_id or "none", ctx.chat_id, ctx.mode, bool(ctx.manual),
            _num(ctx.source_count), bool(ctx.has_trigger))
    except Exception:  # pragma: no cover - лог не должен ронять прогон
        pass


def log_summary_complete(ctx: RunContext) -> None:
    try:
        logger.info(
            "SUMMARY_COMPLETE | run_id=%s | chat_id=%s | mode=%s | status=%s | "
            "duration_ms=%.0f | source_count=%s | saved_count=%s | "
            "restored_count=%s | threads=%s | paragraphs=%s | cover_status=%s",
            ctx.run_id or "none", ctx.chat_id, ctx.mode, ctx.status,
            ctx.duration_ms(), _num(ctx.source_count), _num(ctx.saved_count),
            _num(ctx.restored_count), _num(ctx.threads), _num(ctx.paragraphs),
            ctx.cover_status or "-")
    except Exception:  # pragma: no cover - лог не должен ронять прогон
        pass


def log_summary_failed(ctx: RunContext) -> None:
    try:
        logger.warning(
            "SUMMARY_FAILED | run_id=%s | chat_id=%s | stage=%s | model=%s | "
            "provider=%s | http_status=%s | error_type=%s | reason=%s | "
            "attempts=%s | duration_ms=%.0f",
            ctx.run_id or "none", ctx.chat_id, ctx.stage or "-",
            ctx.model or "-", ctx.provider or "-", _num(ctx.http_status),
            ctx.error_type or "-", ctx.reason or "-", _num(ctx.attempts),
            ctx.duration_ms())
    except Exception:  # pragma: no cover - лог не должен ронять прогон
        pass


def finish_run(ctx: RunContext) -> None:
    """Единая точка завершения прогона: FAILED при провале, иначе COMPLETE."""
    if ctx.status == STATUS_FAILED:
        log_summary_failed(ctx)
    else:
        log_summary_complete(ctx)


# ── §108: этапы FORMAT/COVER (S7, D2; R17-safe, best-effort) ───────────────

def _elapsed_ms(started: float | None) -> float:
    try:
        return (time.perf_counter() - started) * 1000.0 if started else 0.0
    except Exception:  # pragma: no cover - защитная ветка
        return 0.0


def log_format_start(*, run_id, chat_id, channel) -> float:
    """``FORMAT_START`` (§109): начало серверного форматирования (0 LLM).

    Возвращает монотонную метку старта для ``FORMAT_COMPLETE``/``*_ERROR``.
    """
    try:
        logger.info("FORMAT_START | run_id=%s | chat_id=%s | channel=%s",
                    run_id or "none", chat_id, channel)
    except Exception:  # pragma: no cover - best-effort
        pass
    return time.perf_counter()


def log_format_complete(*, run_id, chat_id, channel, paragraphs,
                        started=None) -> None:
    try:
        logger.info(
            "FORMAT_COMPLETE | run_id=%s | chat_id=%s | channel=%s | "
            "paragraphs=%s | status=ok | duration_ms=%.0f",
            run_id or "none", chat_id, channel, _num(paragraphs),
            _elapsed_ms(started))
    except Exception:  # pragma: no cover - best-effort
        pass


def log_format_error(*, run_id, chat_id, channel, reason) -> None:
    try:
        logger.warning(
            "FORMAT_ERROR | run_id=%s | chat_id=%s | channel=%s | reason=%s "
            "— downgrade", run_id or "none", chat_id, channel,
            _safe_reason(reason) or "-")
    except Exception:  # pragma: no cover - best-effort
        pass


def log_cover_start(*, run_id, chat_id, provider) -> float:
    """``COVER_START``: старт генерации обложки; возвращает метку старта."""
    try:
        logger.info("COVER_START | run_id=%s | chat_id=%s | provider=%s",
                    run_id or "none", chat_id, provider or "-")
    except Exception:  # pragma: no cover - best-effort
        pass
    return time.perf_counter()


def log_cover_complete(*, run_id, chat_id, status, started=None) -> None:
    try:
        logger.info(
            "COVER_COMPLETE | run_id=%s | chat_id=%s | status=%s | "
            "duration_ms=%.0f", run_id or "none", chat_id, status or "-",
            _elapsed_ms(started))
    except Exception:  # pragma: no cover - best-effort
        pass


def log_cover_error(*, run_id, chat_id, provider, error_type, reason,
                    started=None) -> None:
    try:
        logger.warning(
            "COVER_ERROR | run_id=%s | chat_id=%s | provider=%s | "
            "error_type=%s | reason=%s | duration_ms=%.0f",
            run_id or "none", chat_id, provider or "-",
            error_type or "-", _safe_reason(reason) or "-",
            _elapsed_ms(started))
    except Exception:  # pragma: no cover - best-effort
        pass
