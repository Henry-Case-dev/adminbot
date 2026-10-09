"""ASAP 7 (F1, architecture.md §1.1–§1.5) — Direct L1 Planner.

Pre-tool L1 Planner (§1.1): 1 LLM call с компактным контекстом (§1.5)
→ :class:`L1Plan` (JSON-контракт §1.3) → hard gates (force/SILENT→🗿/REACT,
§1.7) → deterministic capability mapping (services/direct_capabilities)
→ L2 Writer (Вербализатор-канал, в direct_chat_service).

Ключевые контракты:
  * нормализация L1 JSON **никогда не бросает**; невалидный ``action`` →
    сигнал bounded repair (ровно 1 повтор с аннотацией ошибки, D14) →
    deterministic legacy fallback (classify_request + demote-матрица);
  * закрытые enum'ы (extent/structure/delivery/tool_policy) — переиспользуют
    множества services/response_extent; ``response_act``/``tone`` — открытый
    словарь (§2.3/§2.4 ТЗ: «не превращать enum в клетку»), кап длины;
  * reaction валидируется против ``ALLOWED_LLM_REACTIONS`` (direct_llm_react);
  * confidence clamp [0,1]; бакеты low <0.5 / medium <0.75 / high ≥0.75;
    семантика low: capabilities НЕ исполняются (reason ``low_confidence``),
    SILENT демотируется в дет. матрицу (решает вызывающий);
  * model slot §1.6: hot-first ``models.direct_l1_*``/``keys.direct_l1_api_key``
    (каталог-ключи добавляет F2), env-фолбэк — ClassVar ``DIRECT_L1_*``;
    пусто = inherit main; dedicated-вызов — через транзитный канал
    ``LLMClient._post`` (прецедент ``summary_l1_clusterizer._dedicated_generate``);
  * evidence packet §1.2: deterministic (БЕЗ LLM) — ``redact_secrets`` + кап.

R17: в контекст/пакет попадает только диалоговый контекст Writer-уровня;
в события/логи — enum/числа (см. agentic_events whitelist).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from config.settings import settings

logger = logging.getLogger(__name__)

# ── §1.3: закрытые множества L1 ─────────────────────────────────────────────

ACTIONS = ("reply", "react", "silent")

# extent L1 шире легаси EXTENTS: + one_word/auto (§1.3 схемы).
L1_EXTENTS = ("one_word", "micro", "compact", "auto", "normal", "detailed",
              "longform", "exhaustive")
# «полное» семейство L1 (для is_longform/to_response_plan).
LONGFORM_L1_EXTENTS = frozenset({"detailed", "longform", "exhaustive"})

L1_DELIVERY = ("plain", "rich", "media")       # подмножество DELIVERY_HINTS
L1_TOOL_POLICIES = ("none", "auto")            # подмножество TOOL_POLICIES
EMOTIONAL_MIRRORING = ("none", "light", "medium", "strong")

RESPONSE_ACT_MAX = 32      # §1.3: открытый словарь, ≤32
TONE_MAX = 24              # §1.3: открытый словарь, ≤24
CAPABILITIES_MAX = 8       # bounded список возможностей
CLARIFY_TARGET_MAX = 64

DEFAULT_DIRECT_L1_EVIDENCE_MAX_CHARS = 4000

# §1.5: force/direct-address факты (детерминированные, LLM их не решает).
FORCE_LINE = "прямое обращение к боту: текстовый ответ обязателен"
AUTONOMOUS_LINE = ("автономный контекст (ответ на сообщение бота): действие "
                   "свободное")

_WS_RE = re.compile(r"\s+")


# ── §1.3: L1Plan ─────────────────────────────────────────────────────────────


@dataclass
class L1Plan:
    """Семантический план ответа (§1.3). Internal metadata — в wire-JSON
    Stage-2 не сериализуется; L2 получает hint-строку (plan-блок)."""

    action: str = "reply"
    reaction: str | None = None
    response_act: str = "other"
    extent: str = "auto"
    tone: str = "inherit"
    emotional_mirroring: str = "none"
    structure: str = "chat"
    delivery_hint: str = "plain"
    tool_policy: str = "none"
    capabilities_needed: tuple[str, ...] = ()
    needs_clarification: bool = False
    clarification_target: str | None = None
    confidence: float = 0.0
    confidence_bucket: str = "low"
    source: str = "llm"          # llm | repair | fallback
    form_override: str = ""      # §2.5: явная форма пользователя (после L1)

    def effective_extent(self) -> str:
        """Явная форма пользователя поверх semantic extent (§2.5)."""
        return self.form_override or self.extent

    def is_longform(self) -> bool:
        return self.effective_extent() in LONGFORM_L1_EXTENTS

    def apply_form_override(self, form: str) -> None:
        """Deterministic explicit-form override (§1.8/§2.5): применяется
        ПОСЛЕ L1 поверх semantic extent. Пустая форма — no-op."""
        value = str(form or "").strip().lower()
        self.form_override = value if value in L1_EXTENTS else ""

    def to_response_plan(self):
        """Маппинг на легаси ``ResponsePlan`` (response_extent) — кормит
        существующий дет. downstream: extent-блок, ExecutionGraph,
        rich-gate, media_writer_needed. Никогда не бросает."""
        from services import response_extent as _extent

        extent = self.effective_extent()
        if extent == "one_word":
            rp_extent = "micro"
        elif extent in _extent.EXTENTS:
            rp_extent = extent
        else:
            rp_extent = ""     # auto → без extent-блока (D11)
        act = self.response_act
        task_kind = {"explanation": "explanation", "research": "research",
                     "comparison": "comparison",
                     "summarization": "summarization",
                     "creative": "creative_writing",
                     "historical_recall": "historical_recall",
                     }.get(act, "social_chat")
        return _extent.ResponsePlan(
            task_kind=task_kind,
            extent=rp_extent,
            structure=self.structure if self.structure in
            _extent.STRUCTURES else "chat",
            delivery_hint=self.delivery_hint if self.delivery_hint in
            ("plain", "rich", "media") else "plain",
            tool_policy=self.tool_policy if self.tool_policy in
            ("none", "auto") else "auto",
            source="l1")


def plan_response_mode(plan) -> str:
    """Дет. response_mode для L2 (легаси-алиасы casual/serious/deep_research):
    rich/report → deep_research; полная форма/разбор → serious; болтовня →
    casual. Никогда не бросает."""
    try:
        if plan is None:
            return "serious"
        if getattr(plan, "delivery_hint", "") == "rich" \
                or getattr(plan, "structure", "") == "report":
            return "deep_research"
        if isinstance(plan, L1Plan):
            if plan.is_longform() or plan.structure in (
                    "explanation", "comparison", "summary", "steps"):
                return "serious"
            return "casual"
        if getattr(plan, "is_longform", lambda: False)():
            return "serious"
        return "serious"
    except Exception:      # pragma: no cover - защитная ветка
        return "serious"


# ── §1.3: нормализация (никогда не бросает) ─────────────────────────────────


def _closed(value, valid: tuple[str, ...], default: str) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in valid else default


def _clip_word(value, max_len: int, default: str) -> str:
    """Открытый словарь (§2.3/§2.4): lowercase, трим, схлопывание пробелов,
    кап длины; пустое → default."""
    candidate = _WS_RE.sub(" ", str(value or "")).strip().lower()
    if not candidate:
        return default
    return candidate[:max_len]


def confidence_bucket(confidence: float) -> str:
    """§1.3: low <0.5 / medium <0.75 / high ≥0.75."""
    if confidence < 0.5:
        return "low"
    if confidence < 0.75:
        return "medium"
    return "high"


def normalize_l1_plan(data) -> L1Plan | None:
    """Нормализация L1 JSON → :class:`L1Plan` (§1.3).

    Никогда не бросает. ``None`` — только когда ``action`` отсутствует или
    невалиден (сигнал bounded repair вызывающему)."""
    if not isinstance(data, dict):
        return None
    action = str(data.get("action") or "").strip().lower()
    if action not in ACTIONS:
        return None
    plan = L1Plan(action=action)
    reaction = data.get("reaction")
    if isinstance(reaction, str) and reaction.strip():
        candidate = reaction.strip()
        # §1.3: reaction валидируется против ALLOWED_LLM_REACTIONS;
        # невалидное → None (REACT демотируется вызывающим).
        from services.direct_llm_react import ALLOWED_LLM_REACTIONS
        plan.reaction = candidate if candidate in ALLOWED_LLM_REACTIONS \
            else None
    plan.response_act = _clip_word(data.get("response_act"),
                                   RESPONSE_ACT_MAX, "other")
    plan.tone = _clip_word(data.get("tone"), TONE_MAX, "inherit")
    plan.extent = _closed(data.get("extent"), L1_EXTENTS, "auto")
    from services import response_extent as _extent
    plan.structure = _closed(data.get("structure"), _extent.STRUCTURES,
                             "chat")
    plan.delivery_hint = _closed(data.get("delivery_hint"), L1_DELIVERY,
                                 "plain")
    plan.tool_policy = _closed(data.get("tool_policy"), L1_TOOL_POLICIES,
                               "none")
    plan.emotional_mirroring = _closed(data.get("emotional_mirroring"),
                                       EMOTIONAL_MIRRORING, "none")
    caps = data.get("capabilities_needed")
    if isinstance(caps, (list, tuple)):
        seen: list[str] = []
        for item in caps:
            if not isinstance(item, str):
                continue          # не строка — не имя capability
            name = _clip_word(item, 40, "")
            if name and name not in seen:
                seen.append(name)
            if len(seen) >= CAPABILITIES_MAX:
                break
        plan.capabilities_needed = tuple(seen)
    plan.needs_clarification = bool(data.get("needs_clarification"))
    target = data.get("clarification_target")
    if isinstance(target, str) and target.strip():
        plan.clarification_target = target.strip()[:CLARIFY_TARGET_MAX]
    try:
        conf = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    except Exception:      # pragma: no cover - защитная ветка
        conf = 0.0
    plan.confidence = min(1.0, max(0.0, conf))
    plan.confidence_bucket = confidence_bucket(plan.confidence)
    return plan


def parse_l1_plan(raw) -> L1Plan | None:
    """Разбор ответа L1 (fences/reasoning-срез через существующий
    ``parse_json_object``) → :class:`L1Plan` | ``None`` (invalid JSON)."""
    try:
        from services.system2_handoff import parse_json_object
        return normalize_l1_plan(parse_json_object(raw))
    except Exception:      # pragma: no cover - защитная ветка
        return None


REPAIR_ANNOTATION = (
    "\n\n[SYSTEM] Твой предыдущий ответ не был валидным JSON-планом. "
    "Ответь СТРОГО одной JSON-строкой по схеме из системной роли, без "
    "пояснений и без markdown.")


def build_repair_messages(messages, previous_raw: str) -> list[dict]:
    """Bounded repair (D14): ровно 1 повтор — тот же пакет + аннотация
    ошибки и прежний (мусорный) ответ как user-хвост. Никогда не бросает."""
    try:
        repaired = [dict(m) for m in (messages or [])]
        tail = json_escape_snippet(previous_raw)
        if repaired and repaired[-1].get("role") == "user":
            repaired[-1]["content"] = (
                str(repaired[-1].get("content") or "") + "\n"
                + f"[ПРЕДЫДУЩИЙ ОТВЕТ]: {tail}\n" + REPAIR_ANNOTATION)
        return repaired
    except Exception:      # pragma: no cover - защитная ветка
        return list(messages or [])


def json_escape_snippet(text: str, limit: int = 400) -> str:
    """Однострочный bounded-срез прежнего ответа для repair-аннотации."""
    snippet = _WS_RE.sub(" ", str(text or "")).strip()
    return snippet[:limit]


# ── §1.6: model slot + гейты (hot-first, env-фолбэк) ────────────────────────


@dataclass
class L1ModelSlot:
    """§1.6: резолв L1 slot. ``dedicated=False`` → inherit main."""

    base_url: str = ""
    model: str = ""
    api_key: str = ""
    dedicated: bool = False
    source: str = "main"   # "l1" | "main"


def direct_l1_enabled() -> bool:
    """§1.6: env kill-switch ``DIRECT_L1_ENABLED`` AND product-флаг
    ``flags.direct_l1_enabled`` (каталог-ключ F2; env-AND-семантика §4.3).
    OFF → байт-в-байт прежний pipeline. Резолв per-call, не бросает."""
    try:
        if not bool(getattr(settings, "DIRECT_L1_ENABLED", True)):
            return False
    except Exception:      # pragma: no cover - защитная ветка
        return False
    try:
        from services import hot_config as hot
        return bool(hot.get("flags.direct_l1_enabled", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def l1_fallback_enabled() -> bool:
    """§1.6: ``flags.direct_l1_fallback_enabled`` (default ON): fallback
    на main-модель при отказе configured L1 slot."""
    try:
        from services import hot_config as hot
        return bool(hot.get("flags.direct_l1_fallback_enabled", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def _hot_int(key: str, attr: str, default: int) -> int:
    try:
        from services import hot_config as hot
        value = int(hot.get(key, getattr(settings, attr, default)))
    except Exception:      # pragma: no cover - защитная ветка
        value = default
    return value if value > 0 else default


def l1_context_tokens() -> int:
    """§1.5: кап бюджета L1-контекста (каталог-ключ добавит F2;
    код-дефолт 1600 — ClassVar ``DIRECT_L1_CONTEXT_TOKENS``)."""
    return _hot_int("limits.direct_l1_context_tokens",
                    "DIRECT_L1_CONTEXT_TOKENS", 1600)


def l1_timeout_seconds() -> int:
    """§1.6: timeout L1-вызова (дефолт 15)."""
    return _hot_int("limits.direct_l1_timeout_seconds",
                    "DIRECT_L1_TIMEOUT_SECONDS", 15)


def l1_max_output_tokens() -> int:
    """§1.6: JSON-бюджет вывода L1 (дефолт 512)."""
    return _hot_int("limits.direct_l1_max_output_tokens",
                    "DIRECT_L1_MAX_OUTPUT_TOKENS", 512)


def l1_temperature(default=None):
    """§1.6: температура L1 (дефолт — как у Stage-1: None → температура
    хода). Каталог-ключ добавит F2."""
    try:
        from services import hot_config as hot
        value = hot.get("limits.direct_l1_temperature", None)
        if value is None:
            return default
        return float(value)
    except Exception:      # pragma: no cover - защитная ветка
        return default


def resolve_l1_model(chat_id: int | None = None, *, hot_get=None,
                     settings_obj=None) -> L1ModelSlot:
    """§1.6 ``resolve_l1_model(chat_id)``: configured L1 slot (hot-first
    ``models.direct_l1_base_url``/``models.direct_l1_model_name``/
    ``keys.direct_l1_api_key``; env-фолбэк ``DIRECT_L1_*``) → пусто =
    inherit main. Секрет не логируется (R17). Никогда не бросает."""
    try:
        hg = hot_get
        if hg is None:
            from services import hot_config as hot
            hg = hot.get
        st = settings_obj or settings

        def _read(key: str, attr: str) -> str:
            try:
                return str(hg(key, getattr(st, attr, "")) or "").strip()
            except Exception:      # pragma: no cover - защитная ветка
                return ""

        base = _read("models.direct_l1_base_url", "DIRECT_L1_BASE_URL")
        model = _read("models.direct_l1_model_name", "DIRECT_L1_MODEL_NAME")
        key = _read("keys.direct_l1_api_key", "DIRECT_L1_API_KEY")
        main_base = _read("models.llm_base_url", "LLM_BASE_URL")
        main_model = _read("models.llm_model_name", "LLM_MODEL_NAME")
        main_key = _read("keys.llm_api_key", "LLM_API_KEY")
        if base or model or key:
            return L1ModelSlot(base_url=base or main_base,
                               model=model or main_model,
                               api_key=key or main_key,
                               dedicated=True, source="l1")
        return L1ModelSlot(base_url=main_base, model=main_model,
                           api_key=main_key, dedicated=False, source="main")
    except Exception:      # pragma: no cover - защитная ветка
        return L1ModelSlot(dedicated=False, source="main")


async def dedicated_generate(llm, messages, slot: L1ModelSlot, *,
                             max_output_tokens=None, timeout_seconds=None):
    """Выделенный слот §1.6 через существующий транзитный канал LLMClient.

    Контракт (прецедент ``summary_l1_clusterizer._dedicated_generate``):
    per-call ``base_url``/``model``/``api_key`` через ``_post`` — тот же
    retry/fallback-канал без подмены на глобальную модель. Возврат
    ``(content, usage)``. Ошибки (LLMError/TimeoutError) — вызывающему
    (ladder §1.6)."""
    import asyncio

    payload: dict = {"model": slot.model, "messages": messages}
    if max_output_tokens:
        payload["max_tokens"] = int(max_output_tokens)
    call = llm._post(      # noqa: SLF001 - документированный мост (§1.6)
        "/chat/completions", payload, api_key=slot.api_key,
        base_url=slot.base_url)
    if timeout_seconds:
        response = await asyncio.wait_for(call, timeout=float(timeout_seconds))
    else:
        response = await call
    try:
        data = response.json()
    except ValueError as exc:
        from services.llm_client import LLMBadResponseError
        raise LLMBadResponseError(
            "direct L1 dedicated: invalid JSON response") from exc
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        from services.llm_client import LLMBadResponseError
        raise LLMBadResponseError(
            "direct L1 dedicated: no choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        from services.llm_client import LLMBadResponseError
        raise LLMBadResponseError("direct L1 dedicated: empty content")
    usage = data.get("usage") if isinstance(data, dict) else None
    return content, (usage if isinstance(usage, dict) else None)


# ── §1.5: компактный L1-контекст ────────────────────────────────────────────

L1_WINDOW_MESSAGES = 20       # §1.5: окно последних N (дефолт 20)
L1_PERSONA_FRAME_CHARS = 400  # голова character_block
L1_REPLY_BLOCK_CHARS = 400
L1_WINDOW_LINE_CHARS = 200


def build_l1_context(*, query, current_question: str = "",
                     reply_block: str = "", window=None,
                     speaker: str = "", addressee: str = "",
                     memory_hints: str = "", speech_hints: str = "",
                     capabilities=(), force_line: str = "",
                     persona_frame: str = "",
                     budget_tokens: int | None = None) -> str:
    """§1.5: compact-пакет L1. Полный Writer-контекст L1 НЕ получает.
    Кап бюджета ``limits.direct_l1_context_tokens`` (дефолт 1600):
    дет. деградация — сначала сокращается окно (заголовки/сообщение/
    участники неприкосновенны), затем hint-секции, затем жёсткий кап.
    Никогда не бросает."""
    try:
        sections: list[tuple[str, str]] = []
        current = str(current_question or query or "").strip()
        if current:
            sections.append(("СООБЩЕНИЕ", current))
        if str(reply_block or "").strip():
            sections.append(("ОТВЕТ НА (reply/цитата)",
                             str(reply_block).strip()[:L1_REPLY_BLOCK_CHARS]))
        window_lines = render_window_lines(window, L1_WINDOW_MESSAGES)
        speaker = str(speaker or "неизвестно").strip()
        addressee = str(addressee or "чат").strip()
        if window_lines:
            sections.append(("ПОСЛЕДНИЕ СООБЩЕНИЯ", "\n".join(window_lines)))
        sections.append(("УЧАСТНИКИ",
                         f"Говорящий: {speaker}\nАдресат: {addressee}"))
        if str(memory_hints or "").strip():
            sections.append(("ПАМЯТЬ (срез)", str(memory_hints).strip()))
        if str(speech_hints or "").strip():
            sections.append(("РЕЧЕВОЙ СИГНАЛ", str(speech_hints).strip()))
        caps = [str(c) for c in (capabilities or ()) if str(c).strip()]
        sections.append(("ДОСТУПНЫЕ ВОЗМОЖНОСТИ",
                         ", ".join(caps) if caps else "нет"))
        if str(force_line or "").strip():
            sections.append(("УСЛОВИЯ", str(force_line).strip()))
        if str(persona_frame or "").strip():
            sections.append(("ХАРАКТЕР (кадр)",
                             str(persona_frame).strip()[:L1_PERSONA_FRAME_CHARS]))
        text = "\n\n".join(f"[{name}]\n{body}" for name, body in sections)
        budget = int(budget_tokens) if budget_tokens is not None \
            else l1_context_tokens()
        return _cap_context(text, sections_budget=sections, budget=budget)
    except Exception:          # pragma: no cover - защитная ветка
        return str(query or "")


def _cap_context(text: str, *, sections_budget, budget: int) -> str:
    """Дет. кап §1.5: окно сокращается первым (половина → четверть → 0),
    затем жёсткий символьный кап (~4 символа/токен). Никогда не бросает."""
    try:
        from services.token_counter import count_tokens
        if count_tokens(text) <= budget:
            return text
        for window_cap in (10, 5, 0):
            rebuilt = []
            for name, body in sections_budget:
                if name == "ПОСЛЕДНИЕ СООБЩЕНИЯ":
                    lines = body.splitlines()[-window_cap:] if window_cap \
                        else []
                    if not lines:
                        continue
                    body = "\n".join(lines)
                rebuilt.append(f"[{name}]\n{body}")
            text = "\n\n".join(rebuilt)
            if count_tokens(text) <= budget:
                return text
        char_cap = max(600, budget * 4)
        return text[:char_cap]
    except Exception:          # pragma: no cover - защитная ветка
        return text


def render_window_lines(window, limit: int = L1_WINDOW_MESSAGES) -> list[str]:
    """§1.5: последние N сообщений окна → компактные строки
    ``имя: текст`` (кап на строку). Никогда не бросает."""
    lines: list[str] = []
    try:
        rows = [r for r in (window or []) if isinstance(r, dict)]
        for row in rows[-max(0, int(limit)):]:
            author = str(row.get("author_name") or "?").strip() or "?"
            body = _WS_RE.sub(" ", str(row.get("text") or "")).strip()
            if not body:
                media = str(row.get("media_type") or "").strip()
                body = f"[{media}]" if media else "[медиа]"
            lines.append(f"{author}: {body[:L1_WINDOW_LINE_CHARS]}")
    except Exception:          # pragma: no cover - защитная ветка
        return []
    return lines


# ── §1.2: deterministic evidence packaging (БЕЗ LLM) ────────────────────────


def evidence_max_chars() -> int:
    """Кап evidence-пакета (код-константа; каталога Δ = 0)."""
    try:
        return max(500, int(getattr(
            settings, "DIRECT_L1_EVIDENCE_MAX_CHARS",
            DEFAULT_DIRECT_L1_EVIDENCE_MAX_CHARS)))
    except Exception:      # pragma: no cover - защитная ветка
        return DEFAULT_DIRECT_L1_EVIDENCE_MAX_CHARS


def build_evidence_packet(raw, plan=None, *,
                          max_chars: int | None = None) -> str:
    """§1.2: deterministic evidence packaging — замена LLM-Синтезатора
    (stage-1) в primary path. Из существующих ``tool_results`` /
    ``tool_context`` / ``tool_trace`` (tool_loop) собирает санитизированный
    bounded-текст: ``redact_secrets``, кап символов, статус/ошибка per tool.
    Никогда не бросает; пустой пакет → ""."""
    try:
        from services.system2_handoff import redact_secrets
        lines: list[str] = []
        results = getattr(raw, "tool_results", []) or []
        for entry in list(results)[:12]:
            if not isinstance(entry, dict):
                continue
            tool = str(entry.get("tool") or "?").strip() or "?"
            status = str(entry.get("status") or
                         ("ok" if entry.get("ok") else "error")).strip()
            error = str(entry.get("error_code")
                        or entry.get("error_type") or "").strip()
            lines.append(f"- {tool}: {status}" + (f" ({error})" if error
                                                  else ""))
        if not lines:
            for entry in (getattr(raw, "tool_trace", []) or [])[:12]:
                if isinstance(entry, dict) and entry.get("tool"):
                    ok = bool(entry.get("ok"))
                    lines.append(
                        f"- {entry.get('tool')}: "
                        f"{'ok' if ok else 'error'}")
        context_text = redact_secrets(
            str(getattr(raw, "tool_context", "") or "")).strip()
        parts = []
        if lines:
            parts.append("СТАТУС ИНСТРУМЕНТОВ:\n" + "\n".join(lines))
        if context_text:
            parts.append(context_text)
        packet = "\n\n".join(parts)
        cap = max(500, int(max_chars or evidence_max_chars()))
        return packet[:cap]
    except Exception:          # pragma: no cover - защитная ветка
        return ""


# ── §1.1: plan-блок для L2 Writer ───────────────────────────────────────────


def build_l2_plan_block(plan: L1Plan | None, *, rejected=(),
                        clarification: bool = False,
                        low_confidence: bool = False) -> str:
    """Hint-блок плана для L2 Writer (system/user данные, БЕЗ механического
    штампа: §2.4 ТЗ — L2 видит plan как hint-строку). Языковая дисциплина
    D11: без «коротко»/«по делу». Никогда не бросает."""
    try:
        if plan is None:
            return ""
        lines: list[str] = ["<Response_Plan>",
                            f"действие: {str(plan.action or 'reply')}"]
        act = str(plan.response_act or "other")
        if act and act != "other":
            lines.append(f"смысловой акт ответа: {act}")
        tone = str(plan.tone or "inherit")
        if tone and tone != "inherit":
            lines.append(f"тон: {tone}")
        mirroring = str(plan.emotional_mirroring or "none")
        if mirroring and mirroring != "none":
            lines.append(f"зеркалирование эмоций собеседника: {mirroring}")
        note = rejected_note(rejected)
        if note:
            lines.append(note)
        if low_confidence:
            lines.append("уверенность плана низкая: опирайся на контекст "
                         "разговора, а не на подсказки плана.")
        if clarification:
            lines.append("Задача неразрешима без уточнения: сформулируй "
                         "РОВНО один конкретный уточняющий вопрос по "
                         "недостающей цели. Ничего кроме вопроса не пиши.")
        lines.append("</Response_Plan>")
        return "\n".join(lines)
    except Exception:      # pragma: no cover - защитная ветка
        return ""


def rejected_note(rejected) -> str:
    """Честная пометка L2 «недоступно» (переиспользует direct_capabilities;
    локальный алиас против циклического импорта не нужен — модуль листовой).
    Никогда не бросает."""
    try:
        from services import direct_capabilities as _caps
        return _caps.rejected_note(rejected)
    except Exception:      # pragma: no cover - защитная ветка
        return ""


# ── §1.6 ladder: deterministic legacy fallback ──────────────────────────────


def fallback_plan(query, *, action: str = "reply",
                  allowed_actions=("REPLY",)) -> L1Plan:
    """Deterministic safe fallback (§1.6): classify_request + прежняя
    demote-матрица (action задаёт вызывающий из pre_action). L1Plan с
    ``source="fallback"``; capabilities — из дет. плана (tool_policy auto →
    фолбэк-семантика без capabilities: model-driven цикл сохраняется)."""
    from services import response_extent as _extent
    try:
        legacy = _extent.classify_request(query)
    except Exception:      # pragma: no cover - защитная ветка
        legacy = _extent.ResponsePlan(source="default")
    act = str(action or "reply").lower()
    if act not in ACTIONS:
        act = "reply"
    if act != "reply" and "SILENT" not in {str(a).upper() for a in
                                           (allowed_actions or ())} \
            and act == "silent":
        act = "reply"          # allowed-семантика §1.7 сохраняется
    extent = legacy.extent if legacy.extent in L1_EXTENTS else "auto"
    plan = L1Plan(
        action=act,
        response_act="other",
        extent=extent,
        structure=legacy.structure,
        delivery_hint=legacy.delivery_hint if legacy.delivery_hint in
        L1_DELIVERY else "plain",
        tool_policy=legacy.tool_policy if legacy.tool_policy in
        L1_TOOL_POLICIES else "none",
        capabilities_needed=(),
        confidence=0.0,
        confidence_bucket="low",
        source="fallback")
    return plan


# ── §1.5: R17-whitelist события (эмиссия через agentic_events) ──────────────


def emit_l1_plan_event(*, run_id=None, chat_id=None, message_id=None,
                       plan: L1Plan | None, requested=(), resolved=(),
                       inherited: bool = False, fallback: str = "",
                       latency_ms: int = 0, input_chars: int = 0,
                       source: str = "l1") -> None:
    """``L1_PLAN`` (§1.5, R17-whitelist поля; fail-open)."""
    try:
        from services.agentic_events import L1_PLAN, emit_agentic_event
        p = plan or L1Plan()
        emit_agentic_event(
            L1_PLAN, run_id=run_id, chat_id=chat_id, message_id=message_id,
            action=str(p.action or "reply"),
            response_act=str(p.response_act or "other"),
            extent=str(p.effective_extent() or "auto"),
            tone=str(p.tone or "inherit"),
            bucket=str(p.confidence_bucket or "low"),
            capabilities=[str(c) for c in (requested or ())],
            tools=[str(t) for t in (resolved or ())],
            inherited=bool(inherited),
            fallback=str(fallback or ""),
            latency_ms=int(max(0, latency_ms)),
            input_chars=int(max(0, input_chars)),
            confidence=float(p.confidence),
            source=str(source or "l1"))
    except Exception:          # pragma: no cover - fail-open
        pass


__all__ = [
    "ACTIONS", "L1_EXTENTS", "LONGFORM_L1_EXTENTS", "L1Plan", "L1ModelSlot",
    "FORCE_LINE", "AUTONOMOUS_LINE", "REPAIR_ANNOTATION",
    "normalize_l1_plan", "parse_l1_plan", "build_repair_messages",
    "confidence_bucket", "direct_l1_enabled", "l1_fallback_enabled",
    "l1_context_tokens", "l1_timeout_seconds", "l1_max_output_tokens",
    "l1_temperature", "resolve_l1_model", "dedicated_generate",
    "build_l1_context", "render_window_lines", "build_evidence_packet",
    "fallback_plan", "plan_response_mode", "emit_l1_plan_event",
    "build_l2_plan_block", "rejected_note",
]
