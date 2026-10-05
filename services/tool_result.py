"""MCA-11 (round 10.37, ADR-1028-13 D1–D4) — единый ToolResult-контракт.

Единственный дом контракта результата инструмента (второго словаря/контура нет):

* 7 статусов ``ok | empty | error | timeout | cancelled | denied |
  delivery_unknown`` + детерминированная деривация из модельно-видимого вывода
  и out-of-band сигналов обвязки (A20: строка с текстом ошибки ≠ ok);
* категории канона 12 (``memory_read/external_read/paid_media/admin``) — метки
  для будущих лимитов, НЕ гейт прав (существующие гейты не меняются);
* ``retryable`` — закрытые правила транзиентных причин (D2);
* сборка канонической envelope-записи (существующие ключи + аддитивные:
  ``category/retryable/duration_ms/usage/external_operation_id/evidence_refs/
  partial``) — R17-safe, сырой output не персистится;
* idempotency key side effects (D3): детерминированный ``sha1-16``
  (``chat|corr|tool|args_fingerprint|op_kind``), в события/envelope — только
  хэш; провайдерская идемпотентность — где API её поддерживает, exactly-once
  не обещается;
* единицы/область/значение/причина лимитов (D4/T-4951) — закрытые виды
  (финансы/токены контекста/concurrency/размер/deadline/антиспам/актуальность),
  UI-рендер — mca-17c;
* usage-детализация (D4): ``cost_usd=null`` при неизвестной цене (unknown ≠ 0).

K1 ``MCA_TOOL_RESULT_ENABLED`` (env-only, ON): OFF → tool_loop работает
legacy-путём 2.58.56 байт-в-байт (``ok/error/skipped``, прежние ключи).
K2 ``MCA_TOOL_DELIVERY_GUARD_ENABLED``: OFF → без новой деривации ключа/
маркировки ``delivery_unknown``. K3 ``MCA_COST_ACCOUNTING_ENABLED``: OFF → без
новых точек записи расходов.
"""
from __future__ import annotations

import hashlib
import json
import re

from config.settings import settings

# ── статусы (закрытый набор — 7; ADR D1) ────────────────────────────────────
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_ERROR = "error"
STATUS_TIMEOUT = "timeout"
STATUS_CANCELLED = "cancelled"
STATUS_DENIED = "denied"
STATUS_DELIVERY_UNKNOWN = "delivery_unknown"
STATUSES = frozenset({
    STATUS_OK, STATUS_EMPTY, STATUS_ERROR, STATUS_TIMEOUT, STATUS_CANCELLED,
    STATUS_DENIED, STATUS_DELIVERY_UNKNOWN,
})

# ── категории канона 12 (ADR D1; права не расширяются) ──────────────────────
CATEGORY_MEMORY_READ = "memory_read"
CATEGORY_EXTERNAL_READ = "external_read"
CATEGORY_PAID_MEDIA = "paid_media"
CATEGORY_ADMIN = "admin"
CATEGORIES = frozenset({
    CATEGORY_MEMORY_READ, CATEGORY_EXTERNAL_READ, CATEGORY_PAID_MEDIA,
    CATEGORY_ADMIN,
})

#: канон 12 → категория. Неизвестный инструмент → external_read (консервативно),
#: никогда admin (D1).
TOOL_CATEGORIES = {
    "query_chat_memory": CATEGORY_MEMORY_READ,
    "dig_into_lore": CATEGORY_MEMORY_READ,
    "get_recent_history": CATEGORY_MEMORY_READ,
    "get_user_context": CATEGORY_MEMORY_READ,
    "execute_web_search": CATEGORY_EXTERNAL_READ,
    "fetch_article": CATEGORY_EXTERNAL_READ,
    "summarize_video": CATEGORY_EXTERNAL_READ,
    "transcribe_video": CATEGORY_EXTERNAL_READ,
    "download_media": CATEGORY_EXTERNAL_READ,
    "generate_image": CATEGORY_PAID_MEDIA,
    "compile_lore_story": CATEGORY_PAID_MEDIA,
    "get_bot_health": CATEGORY_ADMIN,
}
DEFAULT_CATEGORY = CATEGORY_EXTERNAL_READ

#: Идемпотентные категории (read-only): повтор ≤2 допустим (A2). paid_media —
#: не идемпотентная операция: повтор после успеха/delivery_unknown запрещён (D3).
IDEMPOTENT_CATEGORIES = frozenset({
    CATEGORY_MEMORY_READ, CATEGORY_EXTERNAL_READ, CATEGORY_ADMIN,
})

#: Закрытые транзиентные причины (D2 §2.3).
RETRYABLE_ERROR_CODES = frozenset({
    "timeout", "safe_fetch_timeout", "provider_unavailable",
    "provider_stalled", "rate_limit",
})

#: op_kind для idempotency key (D3).
OP_KIND_TOOL_CALL = "tool_call"
OP_KIND_MEDIA_SUBMIT = "media_submit"

#: Атрибут out-of-band сигнала на ToolContext (R17-safe: коды/числа/id).
SIGNAL_ATTR = "tool_result_signal"

#: Envelope-ключи legacy 2.58.56 (для OFF-паритетного теста/док-ции).
LEGACY_ENVELOPE_KEYS = frozenset({
    "round", "tool", "args_fingerprint", "status", "data", "error_code",
    "error_type", "truncated", "metered", "duplicate", "attempt", "out_chars",
})

#: Envelope-ключи канонической формы (legacy + аддитивные; ADR D1 §2.2).
CANONICAL_ENVELOPE_KEYS = LEGACY_ENVELOPE_KEYS | frozenset({
    "category", "retryable", "duration_ms", "usage", "external_operation_id",
    "evidence_refs", "partial",
})

#: Единицы/область/причина лимитов (D4/T-4951): закрытые виды. UI — mca-17c.
LIMIT_KINDS = {
    "tool_calls": {"unit": "calls", "scope": "chain"},
    "tool_metered_calls": {"unit": "calls", "scope": "chain"},
    "tool_chain_deadline": {"unit": "seconds", "scope": "chain"},
    "tool_same_call": {"unit": "calls", "scope": "call"},
    "money": {"unit": "usd", "scope": "operation"},
    "context_tokens": {"unit": "tokens", "scope": "context"},
    "concurrency": {"unit": "slots", "scope": "process"},
    "payload_size": {"unit": "bytes", "scope": "payload"},
    "antispam": {"unit": "events", "scope": "chat"},
    "freshness": {"unit": "seconds", "scope": "context"},
}

#: R17-safe ограничения на evidence refs.
_MAX_EVIDENCE_REFS = 8
_MAX_REF_CHARS = 64

#: Закрытые payload-статусы → канонический ToolResult (D1 §2.1).
_PAYLOAD_EMPTY_STATUSES = frozenset({"not_found", "unsupported",
                                     "insufficient_output_budget"})
_PAYLOAD_DENIED_STATUSES = frozenset({"skipped", "denied", "disabled"})


def enabled() -> bool:
    """K1 ``MCA_TOOL_RESULT_ENABLED`` (env-only, ON; per-call, не бросает)."""
    try:
        return bool(getattr(settings, "MCA_TOOL_RESULT_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def delivery_guard_enabled() -> bool:
    """K2 ``MCA_TOOL_DELIVERY_GUARD_ENABLED`` (env-only, ON; per-call)."""
    try:
        return bool(getattr(settings, "MCA_TOOL_DELIVERY_GUARD_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def cost_accounting_enabled() -> bool:
    """K3 ``MCA_COST_ACCOUNTING_ENABLED`` (env-only, ON; per-call)."""
    try:
        return bool(getattr(settings, "MCA_COST_ACCOUNTING_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def transient_retries_max() -> int:
    """``MCA_TOOL_TRANSIENT_RETRIES_MAX`` (env-only, default 2; D2).

    Верхняя граница transient-повторов на один идемпотентный вызов для любого
    retry-слоя (mca-11 сам chain-level повторов не добавляет)."""
    try:
        return max(0, int(getattr(settings, "MCA_TOOL_TRANSIENT_RETRIES_MAX", 2)))
    except (TypeError, ValueError):      # pragma: no cover - защитная ветка
        return 2


def category_for(tool: str) -> str:
    """Категория канона 12; неизвестный инструмент → external_read."""
    return TOOL_CATEGORIES.get(str(tool or ""), DEFAULT_CATEGORY)


def is_idempotent(tool: str) -> bool:
    """True — read-only категория (повтор безопасен); paid_media → False."""
    return category_for(tool) in IDEMPOTENT_CATEGORIES


def op_kind_for(tool: str) -> str:
    """Вид операции для idempotency key: платное медиа ≠ обычный вызов."""
    return (OP_KIND_MEDIA_SUBMIT if category_for(tool) == CATEGORY_PAID_MEDIA
            else OP_KIND_TOOL_CALL)


def idempotency_key(chat_id, correlation_id, tool: str,
                    args_fingerprint: str, op_kind: str) -> str:
    """Детерминированный idempotency key side effect (D3, R17-safe).

    ``sha1-16(chat_id|correlation_id|tool|args_fingerprint|op_kind)`` —
    стабилен в пределах хода; сырые аргументы не участвуют (только отпечаток).
    """
    raw = "|".join((
        str(chat_id if chat_id is not None else ""),
        str(correlation_id or ""),
        str(tool or ""),
        str(args_fingerprint or ""),
        str(op_kind or ""),
    ))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def limit_record(kind: str, value=None, reason: str = "") -> dict:
    """Единицы/область/значение/причина лимита (D4/T-4951; R17-safe)."""
    spec = LIMIT_KINDS.get(str(kind or ""), {"unit": "count", "scope": "unknown"})
    record = {"kind": str(kind or ""), "unit": spec["unit"],
              "scope": spec["scope"], "reason": str(reason or "")}
    if value is not None:
        record["value"] = value
    return record


# ── out-of-band сигнал (единственный канал невидимых обвязке деталей) ────────

def set_signal(ctx, signal: dict) -> None:
    """Записать R17-safe сигнал обвязки (fail-open; никогда не бросает)."""
    try:
        setattr(ctx, SIGNAL_ATTR, dict(signal or {}))
    except Exception:      # pragma: no cover - защитная ветка
        pass


def take_signal(ctx) -> dict | None:
    """Забрать сигнал (одноразово) и очистить слот."""
    try:
        value = getattr(ctx, SIGNAL_ATTR, None)
        setattr(ctx, SIGNAL_ATTR, None)
    except Exception:      # pragma: no cover - защитная ветка
        return None
    return value if isinstance(value, dict) else None


def clear_signal(ctx) -> None:
    """Очистить слот сигнала (вызывается на входе dispatch)."""
    try:
        setattr(ctx, SIGNAL_ATTR, None)
    except Exception:      # pragma: no cover - защитная ветка
        pass


# ── деривация статуса/retryable (D1 §2.1/§2.3) ──────────────────────────────

def _payload_error_code(payload: dict) -> str:
    """error_code из payload: error/reason, затем stats.reason (mca-15)."""
    for key in ("error", "reason"):
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()[:64]
    stats = payload.get("stats")
    if isinstance(stats, dict):
        value = stats.get("reason")
        if value is not None and str(value).strip():
            return str(value).strip()[:64]
    return "tool_error"


def _evidence_refs(data) -> list[str]:
    """R17-safe refs из payload: source_id/metric_id/sources[].ref (D1 §2.2)."""
    refs: list[str] = []
    if isinstance(data, dict):
        for key in ("source_id", "metric_id"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                refs.append(value.strip()[:_MAX_REF_CHARS])
        sources = data.get("sources")
        if isinstance(sources, (list, tuple)):
            for item in sources:
                if len(refs) >= _MAX_EVIDENCE_REFS:
                    break
                if isinstance(item, dict):
                    ref = item.get("ref")
                    if isinstance(ref, str) and ref.strip():
                        refs.append(ref.strip()[:_MAX_REF_CHARS])
    out: list[str] = []
    for ref in refs:
        if ref not in out:
            out.append(ref)
        if len(out) >= _MAX_EVIDENCE_REFS:
            break
    return out


def _num(value):
    """int/float (без bool) либо None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _normalize_usage(raw) -> dict:
    """usage-envelope (D1 §2.2): числа/коды; отсутствие → {}.

    Неизвестная стоимость честно ``cost_usd=null`` + ``price_known=false``
    (unknown ≠ 0); ``currency`` — существующий контракт USD."""
    if not isinstance(raw, dict) or not raw:
        return {}
    out: dict = {}
    for key in ("input_tokens", "output_tokens"):
        value = _num(raw.get(key))
        out[key] = int(value) if value is not None else 0
    cached = _num(raw.get("cached_tokens"))
    out["cached_tokens"] = int(cached) if cached is not None else None
    cost = _num(raw.get("cost_usd"))
    out["cost_usd"] = round(float(cost), 6) if cost is not None else None
    out["price_known"] = bool(raw.get("price_known"))
    out["currency"] = str(raw.get("currency") or "USD")
    version = raw.get("price_version")
    out["price_version"] = (str(version) if version else None)
    out["source"] = str(raw.get("source") or "")
    return out


def usage_detail(usage, *, source: str = "", price_version: str | None = None,
                 tokens_estimated: bool | None = None) -> dict:
    """Детализация usage для ``mca_events.usage_json`` (D4, R17-safe).

    unknown ≠ 0: нет цены → ``cost_usd=None`` + ``price_known=false`` (не
    заявление о нуле). Валюта — USD; ``price_version`` — из llm_pricing."""
    env = _normalize_usage(usage) if isinstance(usage, dict) else {}
    detail = {
        "input_tokens": int(env.get("input_tokens") or 0),
        "output_tokens": int(env.get("output_tokens") or 0),
        "cached_tokens": env.get("cached_tokens"),
        "tokens_estimated": bool(tokens_estimated),
        "cost_usd": env.get("cost_usd"),
        "price_known": bool(env.get("price_known")),
        "currency": str(env.get("currency") or "USD"),
        "price_version": (price_version or env.get("price_version")
                          or "unknown"),
        "source": str(source or env.get("source") or ""),
    }
    return detail


# ── tools.chain v2: стадийные события execute/deliver/account (D6) ──────────
# AMEND реестра mca-17a: stages_to_events execute→tool_call,
# deliver→tool_delivery, account→tool_accounting. Notable-only (терминал
# вызова с ошибкой/отказом/отменой, `delivery_unknown`, accounting-unknown);
# K4 `MCA_TOOL_CHAIN_STAGES_ENABLED` OFF → событий нет. R17-safe: коды/числа/
# `args_fingerprint`; без текстов/аргументов. UI не делается (mca-17c).

CHAIN_STAGE_EVENTS = {
    "execute": "tool_call",
    "deliver": "tool_delivery",
    "account": "tool_accounting",
}

#: Notable-терминалы стадии execute (ok/empty — не шумят; delivery_unknown
#: обрабатывает стадия deliver).
CHAIN_EXECUTE_NOTABLE_STATUSES = frozenset({
    STATUS_ERROR, STATUS_TIMEOUT, STATUS_CANCELLED, STATUS_DENIED,
})

#: Legacy chain-коды → коды единого словаря `mca_events.REASON_CODES`
#: (spec §3: tool_step_limit/deadline_exceeded/financial_limit_reached уже
#: существуют; второго словаря нет).
CHAIN_LIMIT_REASON_MAP = {
    "chain_timeout": "deadline_exceeded",
    "chain_call_limit": "tool_step_limit",
    "chain_cost_limit": "financial_limit_reached",
}


def chain_stages_enabled() -> bool:
    """K4 ``MCA_TOOL_CHAIN_STAGES_ENABLED`` (env-only, ON; per-call)."""
    try:
        return bool(getattr(settings, "MCA_TOOL_CHAIN_STAGES_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def _stage_reason_code(code: str) -> str:
    """Код из единого словаря: как есть, иначе маппинг chain_* → существующий
    (вне словаря → пусто: событие без выдуманного кода)."""
    from services import mca_events
    text = str(code or "")
    if text in mca_events.REASON_CODES:
        return text
    return CHAIN_LIMIT_REASON_MAP.get(text, "")


def emit_tool_chain_events(*, tool: str, status: str, chat_id=None,
                           correlation_id=None, args_fingerprint: str = "",
                           duration_ms: int = 0, attempt: int = 0,
                           usage=None, error_code: str = "",
                           chain_limit_code: str = "") -> list:
    """Notable-события стадий tools.chain (D6; fail-open; K4-gated).

    execute → ``tool_call`` при notable-терминале (error/timeout/cancelled/
    denied; chain-лимиты дают mapped reason_code); deliver → ``tool_delivery``
    при ``delivery_unknown``; account → ``tool_accounting`` при usage с
    неизвестной ценой (``cost_unknown``; ``usage_json`` — D4-детализация).
    Возвращает список эмитированных событий (пусто при OFF/не-notable)."""
    if not chain_stages_enabled():
        return []
    try:
        from services import mca_events
        status = str(status or "")
        tool_name = str(tool or "")
        emitted: list = []

        def _emit(stage: str, event_name: str, outcome: str, *,
                  reason_code: str = "", level: str = mca_events.LEVEL_WARN,
                  usage_json=None) -> None:
            fields = {
                "component": "tools",
                "stage": stage,
                "status": status[:60],
                "chat_id": (int(chat_id) if isinstance(chat_id, int)
                            and not isinstance(chat_id, bool) else None),
                "trace_id": (str(correlation_id)
                             if correlation_id else None),
                "duration_ms": int(duration_ms or 0),
                "attempt": int(attempt or 0),
                "entity_ids": {"tool": tool_name,
                               "args_fingerprint": str(args_fingerprint or "")},
            }
            if reason_code:
                fields["reason_code"] = reason_code
            if usage_json is not None:
                fields["usage_json"] = usage_json
            fields = {k: v for k, v in fields.items() if v is not None}
            # Литеральные имена — контракт mca-17a (скан `emit_mca_event`).
            if event_name == "tool_call":
                event = mca_events.emit_mca_event("tool_call", outcome=outcome,
                                                  level=level, **fields)
            elif event_name == "tool_delivery":
                event = mca_events.emit_mca_event("tool_delivery",
                                                  outcome=outcome, level=level,
                                                  **fields)
            else:
                event = mca_events.emit_mca_event("tool_accounting",
                                                  outcome=outcome, level=level,
                                                  **fields)
            if event is not None:
                emitted.append(event)

        if status in CHAIN_EXECUTE_NOTABLE_STATUSES:
            outcome = {
                STATUS_ERROR: mca_events.OUTCOME_FAILED,
                STATUS_TIMEOUT: mca_events.OUTCOME_FAILED,
                STATUS_CANCELLED: mca_events.OUTCOME_CANCELLED,
                STATUS_DENIED: mca_events.OUTCOME_SKIPPED,
            }.get(status, mca_events.OUTCOME_FAILED)
            _emit("execute", "tool_call", outcome,
                  reason_code=_stage_reason_code(chain_limit_code
                                                 or error_code or status))
        elif status == STATUS_DELIVERY_UNKNOWN:
            _emit("deliver", "tool_delivery", mca_events.OUTCOME_PENDING_EXTERNAL,
                  reason_code="delivery_unknown")

        env_usage = usage if isinstance(usage, dict) else {}
        if env_usage:
            price_known = bool(env_usage.get("price_known"))
            _emit("account", "tool_accounting",
                  (mca_events.OUTCOME_SUCCESS if status == STATUS_OK
                   else mca_events.OUTCOME_FAILED),
                  reason_code=("" if price_known else "cost_unknown"),
                  level=(mca_events.LEVEL_INFO if price_known
                         else mca_events.LEVEL_WARN),
                  usage_json=usage_detail(
                      env_usage, source=str(env_usage.get("source") or "")))
        return emitted
    except Exception:      # fail-open: наблюдаемость не рвёт поток
        return []


def _retryable(status: str, error_code: str, tool: str, signal) -> bool:
    """Закрытые правила D2 §2.3 + явный transient-сигнал адаптера (M-MCA02-3)."""
    if status in (STATUS_DELIVERY_UNKNOWN, STATUS_DENIED, STATUS_CANCELLED,
                  STATUS_EMPTY, STATUS_OK):
        return False
    if not is_idempotent(tool):
        return False
    if status == STATUS_TIMEOUT or error_code in RETRYABLE_ERROR_CODES:
        return True
    if isinstance(signal, dict) and signal.get("retryable") is True:
        return True
    return False


def classify_output(tool: str, output, *, signal: dict | None = None) -> dict:
    """Каноническая деривация ToolResult (K1 ON; D1 §2.1/§2.3).

    A20-инвариант: любой текст, начинающийся с ``ОШИБКА``, и JSON
    ``status:"error"`` дают ``error``/``timeout`` — никогда ``ok``.
    ``data`` сохраняет payload как есть (контракт mca-15 не подменяется).
    """
    text = str(output or "")
    stripped = text.strip()
    info = {
        "status": STATUS_OK, "error_code": "", "error_type": "",
        "data": None, "truncated": False, "partial": False,
        "retryable": False, "evidence_refs": [], "usage": {},
        "external_operation_id": None,
    }
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            info["data"] = payload
            if payload.get("truncated"):
                info["truncated"] = True
            pstatus = str(payload.get("status") or "").strip().lower()
            if pstatus == "error":
                message = str(payload.get("message") or "").lower()
                if "отключ" in message or "выключ" in message:
                    # Отказ политикой/флагом/правами (D1 §2.1): «... отключена».
                    info["status"] = STATUS_DENIED
                    info["error_code"] = "disabled"
                else:
                    info["status"] = STATUS_ERROR
                    code = _payload_error_code(payload)
                    info["error_code"] = code
                    info["error_type"] = code[:120]
            elif pstatus in _PAYLOAD_EMPTY_STATUSES:
                info["status"] = STATUS_EMPTY
                info["error_code"] = ("stats_unsupported"
                                      if pstatus == "unsupported" else pstatus)
            elif pstatus in _PAYLOAD_DENIED_STATUSES:
                info["status"] = STATUS_DENIED
                info["error_code"] = _payload_error_code(payload)
            elif pstatus == "partial":
                info["partial"] = True
    if info["status"] == STATUS_OK and text.startswith("ОШИБКА"):
        info["status"] = STATUS_ERROR
        low = text.lower()
        if "неизвестный инструмент" in text:
            info["error_code"] = "unknown_tool"
        elif "timeout" in low:
            info["status"] = STATUS_TIMEOUT
            info["error_code"] = "timeout"
        elif "отключен" in low or "выключен" in low:
            # Отказ политикой/флагом/правами до исполнения (D1 §2.1).
            info["status"] = STATUS_DENIED
            info["error_code"] = "disabled"
        else:
            info["error_code"] = "tool_error"
        match = re.match(r"ОШИБКА[^:]*:\s*(.+)$", stripped)
        info["error_type"] = (match.group(1).strip() if match else "error")[:120]
    if info["status"] == STATUS_OK and text.startswith("Инструмент ") \
            and "отключен" in text.lower():
        # Отказ политикой/флагом до исполнения (D1 §2.1): «Инструмент X отключен.»
        info["status"] = STATUS_DENIED
        info["error_code"] = "disabled"
    if not info["truncated"] and stripped.endswith("…"):
        info["truncated"] = True
    if isinstance(signal, dict):
        sstatus = str(signal.get("status") or "").strip().lower()
        if sstatus in STATUSES:
            info["status"] = sstatus
        code = str(signal.get("error_code") or "").strip()
        if code:
            info["error_code"] = code[:64]
            if not info["error_type"]:
                info["error_type"] = code[:120]
        stage = str(signal.get("stage") or "").strip()
        if stage:
            data = dict(info["data"]) if isinstance(info["data"], dict) else {}
            data["stage"] = stage[:40]
            info["data"] = data
        reason = str(signal.get("reason") or "").strip()
        if reason and not info["error_type"]:
            info["error_type"] = reason[:120]
        ext = signal.get("external_operation_id")
        if ext is not None and str(ext).strip():
            info["external_operation_id"] = str(ext).strip()[:64]
        if signal.get("partial") is not None:
            info["partial"] = bool(signal["partial"])
        usage = signal.get("usage")
        if isinstance(usage, dict) and usage:
            info["usage"] = _normalize_usage(usage)
        refs = signal.get("evidence_refs")
        if isinstance(refs, (list, tuple)):
            for ref in refs:
                if len(info["evidence_refs"]) >= _MAX_EVIDENCE_REFS:
                    break
                if isinstance(ref, str) and ref.strip():
                    info["evidence_refs"].append(
                        ref.strip()[:_MAX_REF_CHARS])
    if not info["evidence_refs"]:
        info["evidence_refs"] = _evidence_refs(info["data"])
    # Таймаут-код (payload/текст/сигнал) → канонический `timeout` (D1 §2.1).
    if info["status"] == STATUS_ERROR \
            and info["error_code"] in ("timeout", "safe_fetch_timeout"):
        info["status"] = STATUS_TIMEOUT
    info["retryable"] = _retryable(info["status"], info["error_code"], tool,
                                   signal)
    return info


def make_envelope(round_index: int, name: str, fingerprint: str, info: dict,
                  *, metered: bool, duplicate: bool, attempt: int,
                  out_chars: int, duration_ms: int = 0) -> dict:
    """Каноническая envelope-запись (legacy-ключи + аддитивные; D1 §2.2)."""
    return {
        "round": int(round_index) + 1,
        "tool": str(name),
        "args_fingerprint": str(fingerprint),
        "status": str(info.get("status") or STATUS_OK),
        "data": info.get("data"),
        "error_code": str(info.get("error_code") or ""),
        "error_type": str(info.get("error_type") or ""),
        "truncated": bool(info.get("truncated")),
        "metered": bool(metered),
        "duplicate": bool(duplicate),
        "attempt": int(attempt),
        "out_chars": int(out_chars),
        "category": category_for(name),
        "retryable": bool(info.get("retryable")),
        "duration_ms": int(duration_ms or 0),
        "usage": info.get("usage") or {},
        "external_operation_id": info.get("external_operation_id"),
        "evidence_refs": list(info.get("evidence_refs") or []),
        "partial": bool(info.get("partial")),
    }
