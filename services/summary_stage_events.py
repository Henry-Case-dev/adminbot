"""UR-26.5/UR-30.4: payload-наблюдаемость стадий Summary (R17-safe).

Единый строитель append-only stage-событий ``RunContext.stage_events``
(схема §50.54, тот же словарь ключей, что ``summary_l2_review._stage_event``)
с аддитивными полями наблюдаемости payload'а стадии:

  * ``model``/``provider`` — модель и host провайдера (без пути/ключа);
  * ``finish_reason`` — код завершения стадии (ok/parse-исход/transport);
  * ``usage`` — ``{input_tokens, output_tokens}`` (числа или None);
  * ``chars`` — размер сырого текста стадии (число);
  * ``text_digest`` — digest произведённого текста (``turn_trace.text_digest``,
    blake2s 16 hex; НИКАКОГО сырого текста — R17);
  * ``document_digest`` — digest канонического plain-рендера документа
    (тот же полный текст, что леджер хранения пишет целиком — UR-23.4);
  * ``clock`` — машиночитаемое наличие ChatClock-блока в исходящем payload
    стадии (``chat_clock.outbound_clock_meta``) либо честный код отсутствия
    (``{"clock_included": false, "skip_reason": "..."}``);
  * ``decision`` — явное кодовое решение стадии (repair/correction/supervisor),
    никаких молчаливых fallback'ов.

Инварианты: только числа/коды/id/digest; best-effort (ошибка события не роняет
стадию); ΔDDL=0 (существующий in-memory ``stage_events`` + проекция Inspector);
новых таблиц и сырых текстов нет.
"""
from __future__ import annotations

import time
from typing import Any

__all__ = [
    "STAGE_L1_PLAN", "STAGE_L2_WRITER", "STAGE_L2_REVIEWER", "STAGE_REVISION",
    "STAGE_REPAIR",
    "text_digest", "clock_meta", "build_event", "record",
    "document_plain_digest",
]

#: Имена стадий в payload-матрице UR-30.4 (stage1/stage2/reviewer/repair).
STAGE_L1_PLAN = "l1_plan"
STAGE_L2_WRITER = "l2_writer"
STAGE_L2_REVIEWER = "l2_reviewer"
STAGE_REVISION = "revision"
STAGE_REPAIR = "repair"


def text_digest(text) -> str:
    """Digest текста по конвенции ``services/turn_trace`` (blake2s 16 hex)."""
    try:
        from services.turn_trace import text_digest as _impl
        return _impl(text)
    except Exception:      # pragma: no cover - best-effort
        return ""


def document_plain_digest(document) -> str | None:
    """Digest канонического plain-рендера документа (полный delivered-текст).

    Тот же рендер, что пишет леджер хранения (``format_plain_text``; UR-23.4:
    леджер хранит полный текст, без preview) — digest события сопоставим с
    доставленным текстом 1:1. None — документа нет/рендер недоступен."""
    if not isinstance(document, dict):
        return None
    try:
        from services.summary_article_formatter import format_plain_text
        rendered = format_plain_text(document)
    except Exception:      # pragma: no cover - best-effort
        return None
    if not rendered:
        return None
    return text_digest(rendered)


def clock_meta(messages, *, chat_id=None) -> dict:
    """Наличие ChatClock-блока в исходящем payload'е стадии (UR-26.7/UR-30.4).

    ``{"clock_included": true, timezone, utc_offset, as_of_utc,
    config_version, phase}`` при наличии блока; честный код отсутствия —
    ``{"clock_included": false, "skip_reason": "no_chat_id" | "no_time_block"}``.
    Коды пропуска совпадают с ``chat_clock.log_clock_call``. Никогда не бросает."""
    if chat_id is None:
        return {"clock_included": False, "skip_reason": "no_chat_id"}
    try:
        from services.chat_clock import outbound_clock_meta
        meta = outbound_clock_meta(messages)
    except Exception:      # pragma: no cover - best-effort
        meta = None
    if not meta:
        return {"clock_included": False, "skip_reason": "no_time_block"}
    return meta


def build_event(stage: str, *, attempt: int = 1, status: str,
                reason_code: str | None = None, started: float | None = None,
                model: str | None = None, provider: str | None = None,
                finish_reason: str | None = None,
                usage: dict | None = None, chars: int | None = None,
                text_digest: str | None = None,
                document_digest: str | None = None,
                clock: dict | None = None, decision: str | None = None,
                input_count: int | None = None,
                output_count: int | None = None) -> dict:
    """Append-only stage event §50.54 + payload-наблюдаемость (R17-safe).

    Ключи совместимы с ``summary_l2_review._stage_event``; новые поля
    аддитивны. ``provider`` — host (без схемы/пути/query/ключа)."""
    return {
        "stage": str(stage),
        "attempt": int(attempt),
        "status": str(status),
        "reason_code": (str(reason_code)[:200] if reason_code else None),
        "started_at": started,
        "finished_at": time.time(),
        "input_count": input_count,
        "output_count": output_count,
        "provider": provider,
        "model": model,
        "finish_reason": (str(finish_reason)[:64] if finish_reason else None),
        "usage": (dict(usage) if isinstance(usage, dict) else None),
        "chars": int(chars) if chars is not None else None,
        "text_digest": (str(text_digest)[:32] if text_digest else None),
        "document_digest": (str(document_digest)[:32]
                            if document_digest else None),
        "clock": (dict(clock) if isinstance(clock, dict) else None),
        "decision": (str(decision)[:64] if decision else None),
    }


def record(ctx: Any, event: dict) -> None:
    """Append-only в ``RunContext.stage_events`` (нет ctx — нет события)."""
    if ctx is None:
        return
    try:
        events = getattr(ctx, "stage_events", None)
        if isinstance(events, list):
            events.append(event)
    except Exception:      # pragma: no cover - best-effort
        pass


def provider_host(base_url) -> str | None:
    """R17-safe host провайдера из base_url (без пути/ключа/query)."""
    if not base_url:
        return None
    try:
        from services.summary_run_log import provider_host as _impl
        return _impl(str(base_url)) or None
    except Exception:      # pragma: no cover - best-effort
        return None
