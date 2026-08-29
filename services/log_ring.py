"""Epic 85 (84.11.1, T-628) — in-memory ring-buffer логов + маскировка секретов.

LogRingHandler(logging.Handler) на root-logger (подключается в bot.py рядом
с basicConfig): collections.deque(maxlen=LOG_RING_MAX_ENTRIES, дефолт 1000),
запись {ts, level, logger, message, exc_text}. exc_text — через
traceback.format_exception, усекается до 4000 символов; без исключения — null.
Filter отбрасывает логгеры logtail* (иначе рекурсия с LogtailHandler).
errors_total = накопленное число записей level >= ERROR с момента старта.

sanitize(text) применяется в emit ДО записи в буфер (R17):
  1. литеральные значения секретов (из param_catalog: secret:true — значения
     из settings/env; плюс пароль из POSTGRES_DSN) → "***";
  2. Authorization: Bearer <token> / "bearer <token>" → Bearer ***;
  3. префиксные паттерны sk-… / gsk_… / or-… / tvly-… → первые 4 символа + "***";
  4. URI-креды ://user:pass@ → ://***@.
"""
import datetime
import logging
import os
import re
import threading
import traceback
from collections import deque
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_EXC_TEXT_MAX_CHARS = 4000   # 84.11.1

_SECRETS: tuple[str, ...] | None = None
_SECRETS_LOCK = threading.Lock()

_BEARER_RE = re.compile(r"(Authorization\s*:\s*Bearer\s+)\S+", re.IGNORECASE)
_BEARER_WORD_RE = re.compile(r"(bearer\s+)[A-Za-z0-9._\-]{12,}", re.IGNORECASE)
_PREFIX_RE = re.compile(r"\b((?:sk|gsk|or|tvly)[-_])[A-Za-z0-9_\-]{6,}")
_URI_CREDS_RE = re.compile(r"(://)([^/\s:@]+):([^/\s@]+)@")


def _collect_secrets() -> tuple[str, ...]:
    """Литеральные секретные значения из каталога (R17): все записи с
    secret:true, у которых в settings/env есть непустое значение."""
    values: list[str] = []
    try:
        from config.settings import settings
        from services.param_catalog import REGISTRY
        for spec in REGISTRY.values():
            if not spec.secret or spec.settings_field is None:
                continue
            raw = getattr(settings, spec.settings_field, None)
            if isinstance(raw, str) and raw.strip():
                values.append(raw)
        dsn = os.getenv("POSTGRES_DSN", "")
        if dsn:
            try:
                parsed = urlparse(dsn)
                if parsed.password:
                    values.append(parsed.password)
            except ValueError:
                pass
    except Exception:  # pragma: no cover — каталог не должен ронять логи
        pass
    return tuple(values)


def sanitize(text: str) -> str:
    """R17 (84.11.1): маскировка секретов. Никогда не бросает."""
    global _SECRETS
    if not text:
        return text
    try:
        if _SECRETS is None:
            with _SECRETS_LOCK:
                if _SECRETS is None:
                    _SECRETS = _collect_secrets()
        result = text
        for secret in _SECRETS:
            result = result.replace(secret, "***")
        result = _BEARER_RE.sub(r"\1***", result)
        result = _BEARER_WORD_RE.sub(r"\1***", result)
        result = _PREFIX_RE.sub(lambda m: m.group(1) + "***", result)
        result = _URI_CREDS_RE.sub(r"\1***@", result)
        return result
    except Exception:  # pragma: no cover — sanitize не должен ронять emit
        return text


class _LogtailFilter(logging.Filter):
    """84.11.1: отбрасывает логгеры logtail* (рекурсия с LogtailHandler)."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith("logtail")


class LogRingHandler(logging.Handler):
    """In-memory ring-buffer логов (deque, maxlen из LOG_RING_MAX_ENTRIES)."""

    def __init__(self, maxlen: int | None = None) -> None:
        super().__init__()
        if maxlen is None:
            try:
                maxlen = int(os.getenv("LOG_RING_MAX_ENTRIES", "1000"))
            except ValueError:
                maxlen = 1000
        self._buffer: deque[dict] = deque(maxlen=max(1, maxlen))
        self._lock = threading.Lock()
        self.errors_total = 0
        self.addFilter(_LogtailFilter())

    @property
    def maxlen(self) -> int:
        return self._buffer.maxlen

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = sanitize(record.getMessage())
            exc_text = None
            if record.exc_info:
                exc_text = "".join(
                    traceback.format_exception(*record.exc_info))
                exc_text = exc_text[:_EXC_TEXT_MAX_CHARS]
                # F3 (R17): трейсбеки тоже проходят sanitize — секреты из
                # переменных/URL в исключениях не утекают в /api/status/logs.
                exc_text = sanitize(exc_text)
            entry = {
                "ts": datetime.datetime.now(
                    datetime.timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": message,
                "exc_text": exc_text,
            }
            with self._lock:
                self._buffer.append(entry)
                if record.levelno >= logging.ERROR:
                    self.errors_total += 1
        except Exception:  # pragma: no cover
            self.handleError(record)

    def get_entries(self, level: str = "INFO", limit: int = 200) -> list[dict]:
        """Записи от НОВЫХ к старым. level: DEBUG|INFO|WARNING|ERROR|CRITICAL|
        ALL — фильтр «не ниже уровня» (дефолт INFO = INFO+WARNING+ERROR+…)."""
        threshold = 0
        if level.upper() != "ALL":
            threshold = logging.getLevelName(level.upper().strip())
            if not isinstance(threshold, int):
                threshold = logging.INFO
        limit = max(1, min(1000, int(limit or 200)))
        with self._lock:
            entries = list(self._buffer)
        if threshold > 0:
            entries = [e for e in entries
                       if logging.getLevelName(e["level"]) >= threshold]
        return entries[-limit:][::-1]

    def get_errors_total(self) -> int:
        return self.errors_total


log_ring = LogRingHandler()


def get_log_ring() -> LogRingHandler:
    return log_ring
