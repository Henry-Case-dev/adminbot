"""ASAP 7 (F1, architecture.md §1.4) — Capability→tools allowlist L1.

Единственный источник маппинга capability (L1) → фактические имена tools
(``services/tool_schemas.py``). Механика §1.4:

  ``resolved = CAPABILITY_TOOLS ∩ active_tools(lore, image)``

  * unknown/hallucinated capability → drop + agentic event
    ``L1_CAPABILITY_REJECTED (capability, reason)`` + честная пометка L2
    «недоступно» (D15). Не ошибка прогона;
  * ``statistics`` — тулa в наборе НЕТ (MCA-15 stats-intent — дет.
    пре-блок, не tool): резолвится в ∅ → честная пометка L2;
  * ``build_tool_plan`` (2+ URL + явное сравнение) остаётся дет. fast-path
    в response_extent — primary источник мульти-тул: capability-подсет,
    анонсируемая в ``chat_with_tools`` (§22 п.10 закрыт).

Никогда не бросает; имена tools сверяются с анонсированным runtime-набором.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# §1.4: статическая таблица (точные имена tool_schemas.py).
CAPABILITY_TOOLS: dict[str, tuple[str, ...]] = {
    "web_search": ("execute_web_search",),
    "fetch_url": ("fetch_article",),
    "chat_history": ("get_recent_history",),
    "chat_memory": ("query_chat_memory",),
    "user_memory": ("get_user_context",),
    "historical_search": ("dig_into_lore", "compile_lore_story"),
    "fact_check": ("fact_check",),
    "image_understanding": ("recognize_image",),
    "media_download": ("download_media",),
    "transcription": ("transcribe_video",),
    "video_summary": ("summarize_video",),
    "image_generation": ("generate_image",),
    # §1.4: тулa нет — дет. пре-блок MCA-15; честная пометка L2 (не error).
    "statistics": (),
}

REASON_UNKNOWN = "unknown_capability"
REASON_NO_TOOL = "no_tool"
REASON_NOT_ACTIVE = "tool_not_active"
REASON_LOW_CONFIDENCE = "low_confidence"


def resolve_capabilities(requested, active_tool_names,
                         *, skip_capabilities=()) -> tuple[list[str],
                                                           list[tuple[str, str]]]:
    """§1.4: ``(resolved_tool_names, rejected[(capability, reason)])``.

    Порядок resolved — по порядку объявления capability (дет.); дубликат
    tool от разных capabilities схлопывается. Неизвестное имя → drop с
    reason; известное без активного тула → ``tool_not_active``; пустая
    таблица (statistics) → ``no_tool``. Никогда не бросает."""
    resolved: list[str] = []
    rejected: list[tuple[str, str]] = []
    active = {str(t or "").strip() for t in (active_tool_names or ())}
    skipped = {str(c or "").strip().lower() for c in (skip_capabilities or ())}
    for raw in (requested or ()):
        name = str(raw or "").strip().lower()
        if not name:
            continue
        if name in skipped:
            rejected.append((name, REASON_LOW_CONFIDENCE))
            continue
        tools = CAPABILITY_TOOLS.get(name)
        if tools is None:
            rejected.append((name, REASON_UNKNOWN))
            continue
        if not tools:
            rejected.append((name, REASON_NO_TOOL))
            continue
        hit = False
        for tool in tools:
            if tool in active and tool not in resolved:
                resolved.append(tool)
                hit = True
        if not hit:
            rejected.append((name, REASON_NOT_ACTIVE))
    return resolved, rejected


def available_capabilities(active_tool_names) -> list[str]:
    """Список capability, которые L1 может запросить при данном
    runtime-наборе (для контекста §1.5): тул активен ИЛИ capability без
    тула (statistics — честно присутствует, резолвится в пометку)."""
    active = {str(t or "").strip() for t in (active_tool_names or ())}
    caps: list[str] = []
    for cap, tools in CAPABILITY_TOOLS.items():
        if not tools or any(t in active for t in tools):
            caps.append(cap)
    return caps


def schemas_for_names(names, schemas) -> list[dict]:
    """Анонсируемый подсет схем: только имена из ``names`` (§1.1: в
    ``chat_with_tools`` уходит ТОЛЬКО resolved-подсет). ``names is None`` →
    полный набор (легаси-семантика). Никогда не бросает."""
    if names is None:
        return [s for s in (schemas or ()) if isinstance(s, dict)]
    wanted = {str(n or "").strip() for n in (names or ())}
    out: list[dict] = []
    for schema in (schemas or ()):
        try:
            name = str(((schema or {}).get("function") or {}).get("name")
                       or "").strip()
        except Exception:      # pragma: no cover - защитная ветка
            continue
        if name and name in wanted:
            out.append(schema)
    return out


def rejected_note(rejected) -> str:
    """Честная пометка L2 «недоступно» (§1.4/D15): одна строка-список;
    пусто → "". Никогда не бросает."""
    items = []
    for cap, reason in (rejected or ()):
        name = str(cap or "").strip()
        if name:
            items.append(f"{name} ({str(reason or 'unknown')})")
    if not items:
        return ""
    return ("Недоступные возможности (инструмента нет — не выдумывай "
            "результат, при необходимости честно скажи об этом): "
            + ", ".join(items))


def emit_capability_rejected(capability, reason, *, chat_id=None,
                             run_id=None) -> None:
    """``L1_CAPABILITY_REJECTED (capability, reason)`` (§1.4; fail-open)."""
    try:
        from services.agentic_events import (L1_CAPABILITY_REJECTED,
                                             emit_agentic_event)
        name = str(capability or "").strip().replace(" ", "_")[:64]
        emit_agentic_event(L1_CAPABILITY_REJECTED,
                           capability=name or "unknown",
                           reason=str(reason or REASON_UNKNOWN),
                           chat_id=chat_id, run_id=run_id)
    except Exception:          # pragma: no cover - fail-open
        pass


__all__ = [
    "CAPABILITY_TOOLS", "REASON_UNKNOWN", "REASON_NO_TOOL",
    "REASON_NOT_ACTIVE", "REASON_LOW_CONFIDENCE", "resolve_capabilities",
    "available_capabilities", "schemas_for_names", "rejected_note",
    "emit_capability_rejected",
]
