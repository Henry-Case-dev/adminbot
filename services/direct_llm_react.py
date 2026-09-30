"""ASAP-3.1 (round 1028, ADR-1028-3 D7) + ASAP-3.2 (round 1029, ADR-1028-5
D11) — LLM REACT + LLM-driven Decision.

**ASAP-3.2 D11 (действующий контракт):** выбор действия REPLY/REACT/SILENT
решает LLM в Stage-1 structured output (§47): один Decision Maker возвращает
``{"action":..., "reaction":..., "reason":...}`` / обычный текст REPLY в ТОМ
ЖЕ вызове (§52 — второй LLM-call запрещён). Алгоритм остаётся ТОЛЬКО hard
gates/cheap safety (§48): force keyword/address → REPLY всегда (гейт ДО
Decision Maker, §49); продуктовые правила задаёт allowed-набор; невалидное
решение → детерминированный fallback по прежней матрице (§51). SILENT
direct-autonomous → 🗿 hardcode (§50). Kill-switch отката линии:
env `DIRECT_LLM_DECISION_ENABLED` (default ON) AND прежние гейты реакций
(`DIRECT_LLM_REACTION_ENABLED` + per-chat `flags.chat_decision_reactions_`
`enabled`) — любой OFF → байт-в-байт прежний алгоритмический decision.

**ASAP-3.1 контракт (режим отката, OFF-паритет):** детерминированная
матрица владеет action, LLM выбирает ТОЛЬКО emoji при action=REACT
(`<Reaction_Task>`, `inject_react_task`/`extract_llm_reaction`).

  * Allowed set = union расширенных A8-наборов (10 Telegram-emoji);
    расширение только целыми Telegram-emoji.
  * Невалидное/отсутствующее значение → детерминированный fallback
    (``_reaction_for_class``/``_stable_reaction_pick``) молча (fail-soft,
    не ошибка пользователю, §31).
  * SILENT→🗿 — единственный hardcode; background SILENT — без 🗿.

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


# ── ASAP-3.2 (ADR-1028-5 D11, §47–§52): LLM решает действие ────────────────
# Один Decision Maker structured output в Stage-1 возвращает
# {"action":"REACT","reaction":"💀","reason":"..."} / {"action":"REPLY"} /
# {"action":"SILENT"} — выбор REPLY/REACT/SILENT за LLM, НЕ за алгоритмом
# (§47). Алгоритм остаётся ТОЛЬКО hard gates/cheap safety (§48): force
# keyword/address → REPLY всегда (гейт ДО Decision Maker); allowed-набор
# действий/реакций — runtime (продуктовые правила); невалидно →
# детерминированный fallback по прежней матрице (features). Второй LLM-call
# ради emoji запрещён (§52): REPLY отвечает обычным текстом в ТОМ ЖЕ вызове,
# REACT/SILENT — той же JSON-строкой.

# Kill-switch отката линии «LLM-driven autonomous decision» (§80; env-only,
# Δ каталога = 0). OFF → байт-в-байт прежний алгоритмический decision
# (матрица A7/ASAP-3 + Reaction_Task-контракт ASAP-3.1).

_DECISION_TASK_TEMPLATE = (
    "<Decision_Task>\n"
    "Ты решаешь, что сделать с сообщением, и сразу исполняешь решение.\n"
    "Доступные действия: {actions}.\n"
    "Если решаешь REPLY — сразу напиши обычный текстовый ответ, как писал бы "
    "всегда (БЕЗ JSON).\n"
    "Если решаешь REACT — поставь эмодзи-реакцию: ответь СТРОГО одной "
    "JSON-строкой без пояснений:\n"
    '{{"action":"REACT","reaction":"<эмодзи из набора>","reason":"кратко"}}\n'
    "Если решаешь SILENT — не отвечай текстом: ответь СТРОГО одной "
    "JSON-строкой:\n"
    '{{"action":"SILENT","reason":"кратко"}}\n'
    "{react_hint}"
    "Учитывай сообщение, контекст разговора, характер, тон и отношения.\n"
    "</Decision_Task>"
)

_REACT_HINT_TEMPLATE = (
    "Разрешённые реакции (только из набора): {allowed}.\n")


def build_decision_instruction(allowed_actions, allowed_reactions=()) -> str:
    """Инструкция Decision Maker (user-блок; system-канон не меняется)."""
    actions = ", ".join(str(a) for a in allowed_actions or ("REPLY",))
    react_hint = ""
    if "REACT" in actions and allowed_reactions:
        react_hint = _REACT_HINT_TEMPLATE.format(
            allowed=", ".join(allowed_reactions))
    return _DECISION_TASK_TEMPLATE.format(actions=actions,
                                          react_hint=react_hint)


def inject_decision_task(payload, allowed_actions,
                         allowed_reactions=()):
    """Добавить `<Decision_Task>` последним user-блоком (fail-open; обе
    формы payload: список messages либо dict с ключом ``messages``)."""
    try:
        instruction = "\n\n" + build_decision_instruction(
            allowed_actions, allowed_reactions)
        if isinstance(payload, dict):
            messages = list(payload.get("messages") or [])
            if not messages:
                return payload
            last = dict(messages[-1])
            last["content"] = str(last.get("content") or "") + instruction
            messages[-1] = last
            adapted = dict(payload)
            adapted["messages"] = messages
            return adapted
        if isinstance(payload, (list, tuple)):
            messages = list(payload)
            if not messages:
                return payload
            last = dict(messages[-1])
            last["content"] = str(last.get("content") or "") + instruction
            messages[-1] = last
            return messages
        return payload
    except Exception:      # pragma: no cover - защитная ветка
        return payload


_DECISION_ACTIONS = frozenset({"REPLY", "REACT", "SILENT"})
# Sentinel: ответ ПОХОЖ на попытку decision JSON (начался с «{»), но не
# распарсился — отправлять такой текст пользователю нельзя; вызывающий
# применяет детерминированный fallback прежней матрицы (§51).
_DECISION_INVALID = {"action": "INVALID", "reaction": None, "reason": None}


def extract_llm_decision(raw: str) -> dict | None:
    """Распознать Decision Maker structured output в ответе Stage-1.

    Возвращает ``{"action", "reaction", "reason"}`` для валидного решения
    REACT/SILENT/REPLY; ``{"action":"INVALID",...}`` — ответ-попытка JSON,
    которую нельзя отправлять как текст (детерминированный fallback);
    ``None`` — обычный текстовый ответ (= REPLY по контракту §52).
    Никогда не бросает.
    """
    if not raw:
        return None
    try:
        candidate = str(raw).strip()
        fence = _FENCE_RE.search(candidate)
        if fence:
            candidate = fence.group(1).strip()
        if not candidate.startswith("{"):
            return None                # обычный текстовый ответ (REPLY)
        try:
            data = json.loads(candidate)
        except ValueError:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start < 0 or end <= start:
                return dict(_DECISION_INVALID)
            try:
                data = json.loads(candidate[start:end + 1])
            except ValueError:
                return dict(_DECISION_INVALID)
        if not isinstance(data, dict):
            return dict(_DECISION_INVALID)
        action = str(data.get("action") or "").strip().upper()
        if action not in _DECISION_ACTIONS:
            return dict(_DECISION_INVALID)
        reaction = data.get("reaction")
        if not isinstance(reaction, str):
            reaction = None
        else:
            reaction = reaction.strip() or None
        reason = data.get("reason")
        return {"action": action, "reaction": reaction,
                "reason": str(reason) if isinstance(reason, str) else None}
    except Exception:      # fail-soft: любое отклонение → обычный текст
        return None


def llm_decision_enabled(reactions_flag: bool) -> bool:
    """Конъюнкция гейтов decision-линии: env `DIRECT_LLM_DECISION_ENABLED`
    (откат линии §80) AND `llm_reaction_enabled(...)` (env + per-chat).
    OFF → прежний алгоритмический decision (байт-в-байт)."""
    try:
        env_on = bool(getattr(settings, "DIRECT_LLM_DECISION_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        env_on = True
    return env_on and llm_reaction_enabled(reactions_flag)


def record_decision_outcome(*, source: str, action: str) -> None:
    """Метрики решения (process-local; R17 — только enum)."""
    try:
        _METRICS["decision_total"] = \
            _METRICS.get("decision_total", 0) + 1
        key = f"decision_{str(source or 'unknown')}_total"
        _METRICS[key] = _METRICS.get(key, 0) + 1
        actions = _METRICS.setdefault("decision_actions", {})
        actions[str(action or "unknown")] = \
            actions.get(str(action or "unknown"), 0) + 1
    except Exception:      # pragma: no cover - защитная ветка
        pass


__all__ = [
    "ALLOWED_LLM_REACTIONS", "build_react_instruction", "inject_react_task",
    "extract_llm_reaction", "llm_reaction_enabled", "record_react_outcome",
    "emit_direct_react", "react_metrics_snapshot",
    # ASAP-3.2 (D11): LLM-driven decision
    "build_decision_instruction", "inject_decision_task",
    "extract_llm_decision", "llm_decision_enabled",
    "record_decision_outcome",
]
