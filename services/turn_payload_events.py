"""UNIFIED-REPLY UR-26.3/UR-26.4 — payload-наблюдаемость стадий Initiative
и Factcheck (R17-safe; ΔDDL=0).

Та же схема события, что у саммари (``services/summary_stage_events``,
§50.54 + аддитивные поля наблюдаемости payload'а стадии):

  * ``model``/``provider`` — модель и host провайдера (без пути/ключа);
  * ``finish_reason`` — код завершения стадии (parsed/parse-invalid/
    transport/fallback);
  * ``usage`` — ``{input_tokens, output_tokens}`` или None (нет данных —
    честная пустота, никаких выдуманных чисел);
  * ``chars``/``text_digest`` — размер и blake2s-16hex digest произведённого
    текста стадии (НИКАКОГО сырого текста — R17);
  * ``clock`` — машиночитаемое наличие ChatClock-блока в исходящем payload
    стадии (``chat_clock.outbound_clock_meta``) либо честный код отсутствия
    (``{"clock_included": false, "skip_reason": "..."}``);
  * ``decision`` — явное кодовое решение стадии (silent/react/reply,
    recheck verdict, tool-loop/plain, validator downgrade, mode), никаких
    молчаливых fallback'ов.

Каналы (оба существующие, второй системы нет):

  * struct-событие §50.54 — возвращается вызывающему (тот же словарь
    ключей, что ``RunContext.stage_events`` саммари; append-only по решению
    владельца контекста);
  * durable-зеркало — существующий ``mca_events.emit_mca_event``:
    event_name = имя стадии, component="turn_payload", ``model``/``provider``/
    ``input_tokens``/``output_tokens`` родными полями, полный payload-блок
    стадии — в существующем JSON-поле ``usage_json``. Новых таблиц/колонок
    нет; контракт mca-13 гейтится и fail-open как прежде.

Инварианты: только числа/коды/id/digest; best-effort (ошибка события не
роняет стадию); никогда не бросает.
"""
from __future__ import annotations

__all__ = [
    "STAGE_INITIATIVE_L1", "STAGE_TOOL_PHASE", "STAGE_INITIATIVE_RECHECK",
    "STAGE_NOSTALGIA_TEXT",
    "STAGE_FC_STAGE1", "STAGE_FC_STAGE2", "STAGE_FC_SHORT_REPLY",
    "STAGE_FC_TEMPORAL_VERDICT", "STAGE_FC_TEMPORAL_VALIDATOR",
    "STAGE_FC_TEMPORAL_VERBALIZE",
    "emit_stage", "text_digest", "clock_meta_messages", "clock_meta_text",
    "llm_model", "llm_provider",
]

#: Initiative (UR-26.3): L1-решение participation (silent/react/reply).
STAGE_INITIATIVE_L1 = "initiative_l1_decision"
#: Общая tool/WebSearch-фаза хода (Direct и Initiative, UR-03/UR-06).
STAGE_TOOL_PHASE = "tool_phase"
#: Recheck инициативы перед отправкой (§18D, verdict-коды).
STAGE_INITIATIVE_RECHECK = "initiative_recheck"
#: Nostalgia-Writer: prepared_text без вымышленного времени (UR-26.3).
STAGE_NOSTALGIA_TEXT = "nostalgia_text"

#: Factcheck (UR-26.4): Stage-1 аналитик (single/tool-loop — decision).
STAGE_FC_STAGE1 = "factcheck_stage1"
#: Factcheck Stage-2 вербализатор (response_mode/short — decision).
STAGE_FC_STAGE2 = "factcheck_stage2"
#: Короткий персона-ответ фактчека (в образе, TimeContext — fix).
STAGE_FC_SHORT_REPLY = "factcheck_short_reply"
#: Temporal verdict (+ claim-time/publication separation markers).
STAGE_FC_TEMPORAL_VERDICT = "temporal_verdict"
#: Temporal validator (validated/corrected/failed — downgrade-коды).
STAGE_FC_TEMPORAL_VALIDATOR = "temporal_validator"
#: Temporal verbalizer (server_time маркер снапшота оценки).
STAGE_FC_TEMPORAL_VERBALIZE = "temporal_verbalize"

_COMPONENT = "turn_payload"

# допустимые исходы стадии → константы контракта mca-13
_OUTCOME_MAP = {
    "success": "success",
    "skipped": "skipped",
    "error": "failed",
}


def text_digest(text) -> str:
    """Digest текста по конвенции ``services/turn_trace`` (blake2s 16 hex)."""
    try:
        from services.turn_trace import text_digest as _impl
        return _impl(text)
    except Exception:      # pragma: no cover - best-effort
        return ""


def clock_meta_messages(messages, *, chat_id=None) -> dict:
    """Наличие ChatClock-блока в исходящем payload'е стадии (UR-26.7).

    Те же коды пропуска, что ``summary_stage_events.clock_meta``."""
    try:
        from services.summary_stage_events import clock_meta
        return clock_meta(messages, chat_id=chat_id)
    except Exception:      # pragma: no cover - best-effort
        return {"clock_included": False, "skip_reason": "no_time_block"}


def clock_meta_text(user_text, *, chat_id=None) -> dict:
    """То же для стадии, чей outbound — одиночный user-content (строка)."""
    return clock_meta_messages(
        [{"role": "user", "content": str(user_text or "")}],
        chat_id=chat_id)


def llm_model(llm) -> str | None:
    """Фактическая модель клиента (R17-safe; двойник без атрибутов → None)."""
    try:
        value = str(getattr(llm, "_chat_model", "") or "").strip()
        return value or None
    except Exception:      # pragma: no cover - best-effort
        return None


def llm_provider(llm) -> str | None:
    """Host провайдера клиента (без пути/ключа; R17)."""
    try:
        from services.summary_stage_events import provider_host
        return provider_host(getattr(llm, "_base_url", None))
    except Exception:      # pragma: no cover - best-effort
        return None


def emit_stage(stage: str, *, outcome: str, chat_id=None,
               correlation_id: str | None = None,
               model: str | None = None, provider: str | None = None,
               finish_reason: str | None = None, usage: dict | None = None,
               chars=None, text_digest: str | None = None,
               clock: dict | None = None, decision: str | None = None,
               attempt: int = 1, reason_code: str | None = None,
               started=None, input_count: int | None = None,
               output_count: int | None = None) -> dict:
    """Событие payload-наблюдаемости стадии (R17-safe; никогда не бросает).

    Возвращает struct-событие §50.54 (те же ключи, что саммари) и
    зеркалит его в существующий durable-канал ``mca_events`` (usage_json —
    существующее JSON-поле; ΔDDL=0). Ошибка наблюдаемости не рвёт стадию."""
    try:
        from services import summary_stage_events as _sse
        event = _sse.build_event(
            stage, attempt=int(attempt or 1), status=str(outcome or "error"),
            reason_code=reason_code, started=started, model=model,
            provider=provider, finish_reason=finish_reason, usage=usage,
            chars=chars, text_digest=text_digest, clock=clock,
            decision=decision, input_count=input_count,
            output_count=output_count)
    except Exception:      # pragma: no cover - best-effort
        return {}
    try:
        from services import mca_events
        mca_outcome = _OUTCOME_MAP.get(str(outcome or ""),
                                       mca_events.OUTCOME_FAILED)
        payload = {key: event[key] for key in
                   ("status", "reason_code", "finish_reason", "usage",
                    "chars", "text_digest", "clock", "decision",
                    "input_count", "output_count")
                   if event.get(key) is not None}
        mca_events.emit_mca_event(
            str(stage), outcome=mca_outcome,
            level="INFO" if mca_outcome == "success" else "WARN",
            component=_COMPONENT, stage=str(stage),
            trace_id=str(correlation_id) if correlation_id else None,
            chat_id=chat_id, model=str(model) if model else None,
            provider=str(provider) if provider else None,
            input_tokens=_usage_token(usage, "input_tokens"),
            output_tokens=_usage_token(usage, "output_tokens"),
            usage_json=payload)
    except Exception:      # pragma: no cover - канал fail-open
        pass
    return event


def _usage_token(usage, key):
    """Число токенов из usage-словаря или None (никаких нулей-подмен)."""
    try:
        if not isinstance(usage, dict):
            return None
        value = usage.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return value
    except Exception:      # pragma: no cover - best-effort
        return None
