"""A9 round1026 (`agentic-events-graph-round1026`, ADR-1026-22 D2/D5/D11) —
единая R17-safe точка эмиссии диагностических событий §49 (+ F0.3
``ANTI_CLICHE_*``) поверх **существующего** structured-logger и in-memory
реестра ``RunSnapshotStore`` (ExecutionGraph).

Границы (D2/D5/D11/D14):
  * это НЕ система аналитики и НЕ второй event-store: тонкая **синхронная**
    обёртка ``emit_agentic_event`` (без ``await``/``create_task``, без
    блокирующего ввода-вывода), которая логирует R17-safe строку
    ``event=<TYPE> | k=v`` и аддитивно пишет событие в существующий
    ``execution_graph_source`` (прецедент F0.3 ``_event``);
  * **kill-switch** ``AGENTIC_EVENTS_ENABLED`` (env-only, default ON) резолвится
    per-call; OFF → 0 событий/узлов, паритет baseline;
  * **закрытый enum** ``AGENTIC_EVENT_TYPES`` = 12 §49-типов + 8
    ``ANTI_CLICHE_*`` = 20; событие вне enum не эмитится;
  * **R17-whitelist**: пропускаются только id/числа/enum-коды/имена
    инструментов/``reason_code``; значения-строки валидируются по строгому
    паттерну **без пробелов** (текст сообщений/досье/промпты в событие не
    попадают). Ключи вне whitelist отбрасываются;
  * **fail-open**: любая ошибка эмиссии/валидации → ``return`` без эффекта;
    основной поток (решение/инструмент/изображение) не меняется.
"""
from __future__ import annotations

import logging
import re
import time

from config.settings import settings

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1"

# ── закрытый enum типов событий (D5/D11) ────────────────────────────────────
# 12 §49-типов (диагностика решений).
DECISION_START = "DECISION_START"
DECISION_COMPLETE = "DECISION_COMPLETE"
TOOL_PLAN_CREATED = "TOOL_PLAN_CREATED"
TOOL_CALL_START = "TOOL_CALL_START"
TOOL_CALL_COMPLETE = "TOOL_CALL_COMPLETE"
TOOL_CALL_FAILED = "TOOL_CALL_FAILED"
REACTION_SENT = "REACTION_SENT"
MESSAGE_IGNORED = "MESSAGE_IGNORED"
IMAGE_CONTEXT_RESOLVED = "IMAGE_CONTEXT_RESOLVED"
IMAGE_GENERATION_START = "IMAGE_GENERATION_START"
IMAGE_GENERATION_COMPLETE = "IMAGE_GENERATION_COMPLETE"
IMAGE_GENERATION_FAILED = "IMAGE_GENERATION_FAILED"

# 8 F0.3 ANTI_CLICHE_*-событий (воркер; в чат-граф не форсируются, D11).
ANTI_CLICHE_UPDATE_START = "ANTI_CLICHE_UPDATE_START"
ANTI_CLICHE_MODEL_REQUEST = "ANTI_CLICHE_MODEL_REQUEST"
ANTI_CLICHE_MODEL_RESPONSE = "ANTI_CLICHE_MODEL_RESPONSE"
ANTI_CLICHE_PARSE_ERROR = "ANTI_CLICHE_PARSE_ERROR"
ANTI_CLICHE_DEDUP_COMPLETE = "ANTI_CLICHE_DEDUP_COMPLETE"
ANTI_CLICHE_SAVE_COMPLETE = "ANTI_CLICHE_SAVE_COMPLETE"
ANTI_CLICHE_UPDATE_COMPLETE = "ANTI_CLICHE_UPDATE_COMPLETE"
ANTI_CLICHE_UPDATE_FAILED = "ANTI_CLICHE_UPDATE_FAILED"

CORE_EVENT_TYPES = frozenset({
    DECISION_START, DECISION_COMPLETE, TOOL_PLAN_CREATED, TOOL_CALL_START,
    TOOL_CALL_COMPLETE, TOOL_CALL_FAILED, REACTION_SENT, MESSAGE_IGNORED,
    IMAGE_CONTEXT_RESOLVED, IMAGE_GENERATION_START, IMAGE_GENERATION_COMPLETE,
    IMAGE_GENERATION_FAILED,
})
ANTI_CLICHE_EVENT_TYPES = frozenset({
    ANTI_CLICHE_UPDATE_START, ANTI_CLICHE_MODEL_REQUEST,
    ANTI_CLICHE_MODEL_RESPONSE, ANTI_CLICHE_PARSE_ERROR,
    ANTI_CLICHE_DEDUP_COMPLETE, ANTI_CLICHE_SAVE_COMPLETE,
    ANTI_CLICHE_UPDATE_COMPLETE, ANTI_CLICHE_UPDATE_FAILED,
})
AGENTIC_EVENT_TYPES = frozenset(CORE_EVENT_TYPES | ANTI_CLICHE_EVENT_TYPES)

# ── R17-whitelist полей (D5) ────────────────────────────────────────────────
# Общие R17-safe поля, допустимые у любого события.
_COMMON_FIELDS = frozenset({
    "schema_version", "event", "run_id", "chat_id", "message_id",
    "action", "tools", "reason", "duration_ms", "errors", "ts",
})
# Дополнительные (per-event) R17-safe поля.
_TOOL_FIELDS = frozenset({"tool", "round", "status", "error_code", "out_chars"})
_AGENTIC_EXTRA = frozenset({
    "target", "reaction", "outcome", "resolution", "sources", "facts",
    "slice", "prompt_chars", "latency_ms", "chars", "source", "reason_class",
})
_ANTI_CLICHE_EXTRA = frozenset({
    "capacity", "per_run", "initial_count", "final_count", "candidates",
    "duplicates", "saved", "rounds", "round", "raw_len", "applied_limit",
    "version", "status", "reason", "model", "error_code", "mode", "source",
})

EVENT_FIELDS = {
    DECISION_START: frozenset(),
    DECISION_COMPLETE: frozenset(),
    TOOL_PLAN_CREATED: frozenset(),
    TOOL_CALL_START: _TOOL_FIELDS,
    TOOL_CALL_COMPLETE: _TOOL_FIELDS,
    TOOL_CALL_FAILED: _TOOL_FIELDS,
    REACTION_SENT: frozenset({"outcome", "reaction", "reason"}),
    MESSAGE_IGNORED: frozenset({"action", "reason", "target"}),
    IMAGE_CONTEXT_RESOLVED: frozenset({
        "resolution", "sources", "facts", "slice", "prompt_chars",
        "latency_ms"}),
    IMAGE_GENERATION_START: frozenset({"source", "prompt_chars"}),
    IMAGE_GENERATION_COMPLETE: frozenset({"source", "duration_ms"}),
    IMAGE_GENERATION_FAILED: frozenset({"source", "reason_class"}),
    ANTI_CLICHE_UPDATE_START: _ANTI_CLICHE_EXTRA,
    ANTI_CLICHE_MODEL_REQUEST: _ANTI_CLICHE_EXTRA,
    ANTI_CLICHE_MODEL_RESPONSE: _ANTI_CLICHE_EXTRA,
    ANTI_CLICHE_PARSE_ERROR: _ANTI_CLICHE_EXTRA,
    ANTI_CLICHE_DEDUP_COMPLETE: _ANTI_CLICHE_EXTRA,
    ANTI_CLICHE_SAVE_COMPLETE: _ANTI_CLICHE_EXTRA,
    ANTI_CLICHE_UPDATE_COMPLETE: _ANTI_CLICHE_EXTRA,
    ANTI_CLICHE_UPDATE_FAILED: _ANTI_CLICHE_EXTRA,
}

# ── валидация значений (R17: строки без пробелов = не текст) ───────────────
_ID_FIELDS = frozenset({"run_id", "chat_id", "message_id", "target"})
_NUM_FIELDS = frozenset({
    "duration_ms", "latency_ms", "chars", "prompt_chars", "facts", "slice",
    "out_chars", "round", "rounds", "capacity", "per_run", "initial_count",
    "final_count", "candidates", "duplicates", "saved", "raw_len",
    "applied_limit", "version", "counts", "ts",
})
_MODEL_FIELDS = frozenset({"model"})
# Короткие непустые строки без пробелов (эмодзи-реакция R17-safe).
_SHORT_STR_FIELDS = frozenset({"reaction"})
_LIST_FIELDS = frozenset({"tools", "sources", "errors"})

# Строгая «идентификаторная» форма: буквы/цифры/``_``/``-``/``:``/``.`` и БЕЗ
# пробелов → свободный пользовательский текст (досье/промпт/сообщение) не
# проходит. Длина ограничена.
_IDENT_RE = re.compile(r"^[A-Za-z0-9_\-:.]{0,64}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9_\-./:]{0,64}$")
_SHORT_RE = re.compile(r"^[^\s]{0,8}$")


def agentic_events_enabled() -> bool:
    """A9 kill-switch ``AGENTIC_EVENTS_ENABLED`` (env-only, default ON; D3).

    Резолв per-call; никогда не бросает (fail-safe ON). OFF → эмиссия no-op."""
    try:
        return bool(getattr(settings, "AGENTIC_EVENTS_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def _safe_value(key: str, value):
    """R17-safe нормализация одного поля; небезопасное → ``None`` (drop)."""
    if value is None:
        return None
    if key in _ID_FIELDS:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return value if _IDENT_RE.match(value) else None
        return None
    if key in _NUM_FIELDS:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return value
        return None
    if key in _MODEL_FIELDS:
        return value if (isinstance(value, str)
                         and _MODEL_RE.match(value)) else None
    if key in _SHORT_STR_FIELDS:
        return value if (isinstance(value, str)
                         and _SHORT_RE.match(value)) else None
    if key in _LIST_FIELDS:
        if isinstance(value, (list, tuple, set)):
            items = [str(v) for v in value
                     if isinstance(v, str) and _IDENT_RE.match(str(v))]
            return ",".join(items) if items else None
        if isinstance(value, str) and _IDENT_RE.match(value):
            return value
        return None
    # enum/код: строка без пробелов.
    if isinstance(value, str):
        return value if _IDENT_RE.match(value) else None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    return None


def filter_event_fields(event: str, fields: dict) -> dict:
    """Отфильтровать поля события по R17-whitelist (D5). Неизвестные ключи и
    небезопасные значения отбрасываются; ``None``-значения не сохраняются."""
    allowed = _COMMON_FIELDS | EVENT_FIELDS.get(event, frozenset())
    safe: dict = {}
    if not isinstance(fields, dict):
        return safe
    for key, value in fields.items():
        if key not in allowed:
            continue
        clean = _safe_value(key, value)
        if clean is None:
            continue
        safe[key] = clean
    return safe


def _kv(fields: dict) -> str:
    parts = [f"{key}={value}" for key, value in fields.items()
             if key not in ("event", "schema_version") and value is not None]
    return " | ".join(parts) if parts else "-"


def emit_agentic_event(event: str, **fields) -> None:
    """Единая fail-open точка эмиссии (D2): kill-switch → whitelist →
    structured-log → аддитивная запись в существующий ``RunSnapshotStore``.

    Синхронная, без ``await``/``create_task``/блокирующего ввода-вывода;
    **никогда не бросает** — ошибка эмиссии не влияет на основной поток."""
    try:
        if not agentic_events_enabled():
            return
        if event not in AGENTIC_EVENT_TYPES:
            return
        safe = filter_event_fields(event, fields)
        safe["event"] = event
        safe.setdefault("schema_version", SCHEMA_VERSION)
        safe.setdefault("ts", round(time.time(), 3))
        logger.info("event=%s | %s", event, _kv(safe))
        from services import execution_graph_source
        # `event` передаётся позиционно; из kwargs исключаем, чтобы не дублировать.
        graph_fields = {k: v for k, v in safe.items() if k != "event"}
        execution_graph_source.record_agentic_event(event, **graph_fields)
    except Exception:      # fail-open: поток НЕ рвём
        return
