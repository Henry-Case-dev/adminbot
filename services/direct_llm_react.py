"""ASAP-3.1 (round 1028, ADR-1028-3 D7, spec Q11, §30–§33) — LLM REACT.

Детерминированная decision-матрица ОСТАЁТСЯ владельцем action
REPLY/REACT/SILENT (граница A7, 2-вызовность System 2, await_count==2).
LLM выбирает ТОЛЬКО конкретный emoji при action=REACT — аддитивное поле в
structured output СУЩЕСТВУЮЩЕГО Stage-1 (тот же вызов, что генерирует ответ;
второго/третьего LLM request НЕТ).

  * Allowed set = union расширенных A8-наборов (10 Telegram-emoji);
    расширение только целыми Telegram-emoji.
  * Невалидное/отсутствующее значение → детерминированный fallback
    (``_reaction_for_class``/``_stable_reaction_pick``) молча (fail-soft,
    не ошибка пользователю, §31).
  * LLM вернула action ≠ REACT → матрица не меняется (action владельца —
    детерминированная матрица), reaction → детерминированный fallback.
  * SILENT→🗿 — единственный hardcode, ЛЛМ emoji для SILENT не выбирает
    (§32); background SILENT — без 🗿; Force keyword → всегда REPLY (§33).

Kill-switch: env `DIRECT_LLM_REACTION_ENABLED` (default ON, резолв per-call)
+ per-chat `flags.chat_decision_reactions_enabled` (существующий). Любой
OFF → байт-в-байт детерминированное поведение (шорт-кат без LLM-вызова).

Observability: `DIRECT_REACT {source=llm_decision|deterministic, reaction,
trigger_type}` + счётчики §50 (process-local, grep-able; без raw text).
"""
from __future__ import annotations

import json
import logging
import re

from config.settings import settings

logger = logging.getLogger(__name__)

# Allowed set (spec Q11): union A8-наборов — точный список из фактических
# констант `_REACTION_SETS_BY_CLASS` + `_REACTION_DOUBT_SET` + карта A8.
ALLOWED_LLM_REACTIONS: tuple[str, ...] = (
    "😂", "🤣", "👍", "👌", "❤️", "🔥", "🤨", "🤔", "💀", "🤡",
)
_ALLOWED = frozenset(ALLOWED_LLM_REACTIONS)

# Метрики §50 (process-local; R17 — только числа/enum).
_METRICS: dict = {
    "llm_react_total": 0,
    "llm_react_llm_choice_total": 0,
    "llm_react_fallback_total": 0,
    "distribution": {},
}


def react_metrics_snapshot() -> dict:
    """Снимок счётчиков реакций (§50; distribution — копия dict)."""
    return {
        "llm_react_total": _METRICS["llm_react_total"],
        "llm_react_llm_choice_total": _METRICS["llm_react_llm_choice_total"],
        "llm_react_fallback_total": _METRICS["llm_react_fallback_total"],
        "distribution": dict(_METRICS["distribution"]),
    }


def _record_distribution(reaction: str) -> None:
    _METRICS["distribution"][reaction] = \
        _METRICS["distribution"].get(reaction, 0) + 1


def llm_reaction_enabled(reactions_flag: bool) -> bool:
    """Конъюнкция kill-switch'ей: env `DIRECT_LLM_REACTION_ENABLED` AND
    per-chat `flags.chat_decision_reactions_enabled`. Никогда не бросает."""
    try:
        env_on = bool(getattr(settings, "DIRECT_LLM_REACTION_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        env_on = True
    return env_on and bool(reactions_flag)


# ── Instruction block (user-content, аддитивно — прецедент <dig_result>) ───

_REACT_TASK_TEMPLATE = (
    "<Reaction_Task>\n"
    "Ты выбираешь эмодзи-реакцию на сообщение, а не пишешь ответ. "
    "Выбери ОДНУ реакцию из разрешённого набора: {allowed}.\n"
    "Учитывай сообщение, контекст разговора, характер, тон, отношения и "
    "иронию; одинаковое сообщение не обязано всегда получать одинаковую "
    "реакцию.\n"
    "Ответь СТРОГО одной JSON-строкой без пояснений:\n"
    '{{"action":"REACT","reaction":"<эмодзи из набора>","reason":"кратко"}}\n'
    "</Reaction_Task>"
)


def build_react_instruction() -> str:
    """Инструкция Stage-1 для REACT (user-блок; system-канон не меняется)."""
    return _REACT_TASK_TEMPLATE.format(
        allowed=", ".join(ALLOWED_LLM_REACTIONS))


def inject_react_task(payload):
    """Добавить `<Reaction_Task>` последним user-блоком (порядок блоков
    payload не меняется; fail-open: при любой ошибке payload прежний).

    Принимает обе формы payload: список messages (канон `build_messages`)
    либо dict с ключом ``messages``; возвращает ту же форму."""
    try:
        if isinstance(payload, dict):
            messages = list(payload.get("messages") or [])
            if not messages:
                return payload
            last = dict(messages[-1])
            last["content"] = (str(last.get("content") or "") + "\n\n"
                               + build_react_instruction())
            messages[-1] = last
            adapted = dict(payload)
            adapted["messages"] = messages
            return adapted
        if isinstance(payload, (list, tuple)):
            messages = list(payload)
            if not messages:
                return payload
            last = dict(messages[-1])
            last["content"] = (str(last.get("content") or "") + "\n\n"
                               + build_react_instruction())
            messages[-1] = last
            return messages
        return payload
    except Exception:      # pragma: no cover - защитная ветка
        return payload


# ── Парсинг/валидация ответа (§31: backend только валидирует) ──────────────

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_llm_reaction(raw: str) -> str | None:
    """Извлечь и провалидировать reaction из structured output Stage-1.

    Валидно → emoji (source=llm_decision); иначе ``None`` → детерминированный
    fallback (fail-soft молча, §31). Никогда не бросает."""
    if not raw:
        return None
    try:
        candidate = str(raw).strip()
        fence = _FENCE_RE.search(candidate)
        if fence:
            candidate = fence.group(1).strip()
        # Строгий JSON; иначе — первый {...} фрагмент.
        try:
            data = json.loads(candidate)
        except ValueError:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start < 0 or end <= start:
                return None
            data = json.loads(candidate[start:end + 1])
        if not isinstance(data, dict):
            return None
        # Матрица — владелец action: LLM не может «передумать» в REPLY.
        if str(data.get("action") or "").strip().upper() != "REACT":
            return None
        reaction = data.get("reaction")
        if not isinstance(reaction, str):
            return None
        reaction = reaction.strip()
        if reaction in _ALLOWED:
            return reaction
        return None
    except Exception:      # fail-soft: любое отклонение → fallback
        return None


def record_react_outcome(*, source: str, reaction: str) -> None:
    """Метрики §50 (llm react count + distribution; R17-safe)."""
    try:
        _METRICS["llm_react_total"] += 1
        if source == "llm_decision":
            _METRICS["llm_react_llm_choice_total"] += 1
        else:
            _METRICS["llm_react_fallback_total"] += 1
        _record_distribution(reaction)
    except Exception:      # pragma: no cover - защитная ветка
        pass


def emit_direct_react(*, chat_id: int | None, message_id: int | None,
                      reaction: str, source: str,
                      trigger_type: str | None) -> None:
    """`DIRECT_REACT {source, reaction, trigger_type}` (§49; fail-open)."""
    try:
        from services.agentic_events import DIRECT_REACT, emit_agentic_event
        emit_agentic_event(DIRECT_REACT, chat_id=chat_id,
                           message_id=message_id, reaction=reaction,
                           source=source,
                           trigger_type=trigger_type or "reply_to_bot")
    except Exception:      # fail-open
        pass


__all__ = [
    "ALLOWED_LLM_REACTIONS", "build_react_instruction", "inject_react_task",
    "extract_llm_reaction", "llm_reaction_enabled", "record_react_outcome",
    "emit_direct_react", "react_metrics_snapshot",
]
