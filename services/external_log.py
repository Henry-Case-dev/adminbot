"""Раунд 10.24 (F2, ADR-1024-1) — единый R17-safe лог внешних API/пайплайнов.

Принцип владельца: **«тихий откат для конечного пользователя ≠ тишина в
серверных логах»**. Каждый сбой внешнего API/фонового пайплайна обязан
оставить в логе причину (статус, усечённое тело ответа стороннего API, фаза
падения), но без утечки секретов.

Дизайн (ADR-1024-1 D1–D5):
  * ``log_external_api`` — одна структурированная строка ``event=ext_api``;
  * ``trace_step`` — ``event=pipeline_step`` (Сон/крон/граф);
  * ``log_dropped`` — ``event=dropped_metric`` (потеря данных видима);
  * ``redact_url`` — URL без query/userinfo (по умолчанию);
  * ``safe_text`` — переиспользует ``log_ring.sanitize`` (НЕ дублирует R17).

Гарантии: ни один аргумент хелпера не несёт auth-материал; ``body`` — уже
полученный текст ответа внешнего API. Хелпер никогда не бросает и не делает
сетевых вызовов (работает на уже полученном ``response``).
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

from config.settings import settings
from services.log_ring import sanitize

REDACTED = "***"

# Секрето-подобные ИМЕНА query-параметров (url-names, не значения). Значения
# таких параметров маскируются при `keep_query=True`.
_SECRET_PARAM_RE = re.compile(
    r"(?i)^(key|token|secret|api[_-]?key|apikey|auth|authorization|"
    r"password|passwd|pwd|sig|signature|access[_-]?token|bearer)$")

# Поля `extra` (trace_step/log_dropped) — только числа/коды/метки; значение
# усекается, чтобы строка не разрасталась.
_EXTRA_VALUE_LIMIT = 200
_STATUS_INFO = frozenset({"ok", "skip", "empty", "duplicate"})
_STATUS_ERROR = frozenset({"error", "dropped"})


# ── конфиг (env-only ClassVar; читаем динамически — тесты monkeypatch'ат) ───


def _enabled() -> bool:
    try:
        return bool(getattr(settings, "EXTERNAL_API_LOGGING_ENABLED", True))
    except Exception:  # pragma: no cover — конфиг не должен ронять лог
        return True


def _body_limit() -> int:
    try:
        return int(getattr(settings, "EXTERNAL_API_LOG_BODY_CHARS", 1024))
    except Exception:  # pragma: no cover
        return 1024


def _log_url_query() -> bool:
    try:
        return bool(getattr(settings, "EXTERNAL_API_LOG_URL_QUERY", False))
    except Exception:  # pragma: no cover
        return False


# ── публичные хелперы ───────────────────────────────────────────────────────


def redact_url(url: str, *, keep_query: bool = False) -> str:
    """URL для лога: без userinfo (``://user:pass@``) и query (по умолчанию).

    ``keep_query=True`` оставляет query, но маскирует секрето-подобные
    параметры. Результат дополнительно прогоняется через ``log_ring.sanitize``
    (секрет-токен в path тоже маскируется). Никогда не бросает → ``""``."""
    try:
        raw = str(url or "").strip()
        if not raw:
            return ""
        parts = urlsplit(raw)
        if parts.scheme and parts.netloc:
            host = parts.hostname or ""
            netloc = host
            if parts.port:
                netloc = f"{host}:{parts.port}"
            base = f"{parts.scheme}://{netloc}{parts.path}"
        else:
            # Относительный/некорректный URL: срезаем query вручную.
            base = raw.split("?", 1)[0]
        if keep_query and parts.query:
            query = _redact_query(parts.query)
            if query:
                base = f"{base}?{query}"
        return sanitize(base)
    except Exception:  # pragma: no cover — не должен ронять лог
        return ""


def _redact_query(query: str) -> str:
    """Query с маскировкой значений секрето-подобных ключей."""
    out: list[str] = []
    for part in str(query).split("&"):
        if not part:
            continue
        key, _, _value = part.partition("=")
        if _SECRET_PARAM_RE.match(key.strip()):
            out.append(f"{key}={REDACTED}")
        else:
            out.append(part)
    return "&".join(out)


def safe_text(text, *, limit: int | None = None) -> str:
    """R17-safe текст: ``sanitize`` + схлопывание пробелов + обрезка.

    ``limit=None`` → ``EXTERNAL_API_LOG_BODY_CHARS`` (default 1024). Идемпотентен
    (повторный вызов не портит) и никогда не бросает (``None``/битый вход →
    ``""``)."""
    try:
        if text is None:
            return ""
        raw = sanitize(str(text))
        raw = " ".join(raw.split())
        cap = _body_limit() if limit is None else int(limit)
        if cap > 0 and len(raw) > cap:
            raw = raw[:cap]
        return raw
    except Exception:  # pragma: no cover — sanitize не должен ронять лог
        return ""


def _fmt_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return safe_text(value, limit=_EXTRA_VALUE_LIMIT)


def _extra_items(extra) -> list[str]:
    """Безопасные ``key=value`` из ``extra`` (только безопасные метки)."""
    items: list[str] = []
    if not isinstance(extra, dict):
        return items
    for key, value in extra.items():
        if value is None:
            continue
        name = re.sub(r"[^A-Za-z0-9_]", "_", str(key or ""))[:48]
        if not name:
            continue
        items.append(f"{name}={_fmt_value(value)}")
    return items


def _emit(logger_obj, level: int, message: str) -> None:
    try:
        if logger_obj is not None:
            logger_obj.log(level, message)
    except Exception:  # pragma: no cover — логирование не должно бросать
        pass


def log_external_api(logger, *, provider=None, method=None, url=None,
                     status=None, reason=None, body=None, duration_ms=None,
                     attempt=None, level: int = logging.INFO) -> None:
    """Одна строка ``event=ext_api`` (статус + усечённое тело внешнего API).

    Kill-switch ``EXTERNAL_API_LOGGING_ENABLED=False`` → не печатает ``url`` и
    ``body``, но сохраняет краткую строку ``provider/status/reason``."""
    try:
        on = _enabled()
        parts = ["[ext]", "event=ext_api"]
        if provider:
            parts.append(f"provider={safe_text(provider, limit=64)}")
        if method:
            parts.append(f"method={safe_text(method, limit=16)}")
        if status is not None:
            parts.append(f"status={_fmt_value(status)}")
        if reason:
            parts.append(f"reason={safe_text(reason, limit=_EXTRA_VALUE_LIMIT)}")
        if on and url:
            parts.append(
                f"url={redact_url(url, keep_query=_log_url_query())}")
        if duration_ms is not None:
            parts.append(f"dur_ms={_fmt_value(duration_ms)}")
        if attempt is not None:
            parts.append(f"attempt={_fmt_value(attempt)}")
        if on and body:
            parts.append(f"body='{safe_text(body)}'")
        _emit(logger, int(level), " ".join(parts))
    except Exception:  # pragma: no cover
        pass


def _level_for_status(status) -> int:
    key = str(status or "").strip().lower()
    if key in _STATUS_INFO:
        return logging.INFO
    if key in _STATUS_ERROR:
        return logging.ERROR
    return logging.WARNING


def trace_step(logger, *, component, step, status, reason=None, chat_id=None,
               extra=None, level: int | None = None) -> None:
    """Одна строка ``event=pipeline_step`` (сквозная трассировка пайплайна).

    ``level=None`` → правило: ``ok/skip/empty/duplicate`` → ``INFO``,
    ``error/dropped`` → ``ERROR``, иначе ``WARNING``. Никогда не бросает."""
    try:
        if level is None:
            level = _level_for_status(status)
        parts = ["[pipeline]", "event=pipeline_step",
                 f"component={safe_text(component, limit=64)}",
                 f"step={safe_text(step, limit=64)}",
                 f"status={safe_text(status, limit=32)}"]
        if reason:
            parts.append(f"reason={safe_text(reason, limit=_EXTRA_VALUE_LIMIT)}")
        if chat_id is not None:
            parts.append(f"chat_id={_fmt_value(chat_id)}")
        parts.extend(_extra_items(extra))
        _emit(logger, int(level), " ".join(parts))
    except Exception:  # pragma: no cover
        pass


def log_dropped(logger, *, component, reason, count=1, chat_id=None,
                extra=None) -> None:
    """``event=dropped_metric`` — потеря данных видима и считается (ERROR)."""
    try:
        parts = ["[pipeline]", "event=dropped_metric",
                 f"component={safe_text(component, limit=64)}",
                 f"reason={safe_text(reason, limit=_EXTRA_VALUE_LIMIT)}",
                 f"count={_fmt_value(count)}"]
        if chat_id is not None:
            parts.append(f"chat_id={_fmt_value(chat_id)}")
        parts.extend(_extra_items(extra))
        _emit(logger, logging.ERROR, " ".join(parts))
    except Exception:  # pragma: no cover
        pass
