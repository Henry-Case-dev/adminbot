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
import time
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

# L1D (22.10.2026): форма Telegram-доставки текстового решения (action=reply).
# "reply" - ответ на конкретное сообщение (target_message_id обязателен),
# "chat" - обычное сообщение без reply-привязки. Пусто/невалидно → "chat"
# (консервативный дефолт: отсутствие решения L1 НИКОГДА не включает reply).
L1_DELIVERY_MODES = ("chat", "reply")

RESPONSE_ACT_MAX = 32      # §1.3: открытый словарь, ≤32
TONE_MAX = 24              # §1.3: открытый словарь, ≤24
CAPABILITIES_MAX = 8       # bounded список возможностей
CLARIFY_TARGET_MAX = 64

# ASAP 8 v6 (D04, §18C.7): execution mode — закрытое множество; явное
# значение от LLM или дет. деривация из capabilities (никогда не тихо).
EXECUTION_MODES = ("none", "simple_tools", "adaptive_tool_chain")

# SOUL-1 (W3, SOUL-05.1): РОВНО ОДНО необязательное поле L1 — совет по приёму
# юмора. Это не приказ быть смешным и не новая личность: значение по умолчанию
# ``none``, невалидное → ``none`` (план не инвалидируется). Приёмы — W4
# (`Humor Craft`); L1 только выбирает уместность.
COMIC_STRATEGIES = ("none", "literalism", "absurd_escalation", "deadpan",
                    "bureaucratic_logic", "unexpected_analogy")


def derive_execution_mode(capabilities_needed) -> str:
    """Дет. деривация mode: есть capabilities → simple_tools, нет → none
    (adaptive выбирается ТОЛЬКО явным значением от LLM)."""
    return "simple_tools" if tuple(capabilities_needed or ()) else "none"

# ASAP 8 (F6, §13.1): allowlisted-поле future-intent — единственная новая ось
# схемы L1. LLM предлагает ЗАКРЫТЫЙ kind + короткую цель; intent в durable
# `mca_intents` пишет СЕРВИС (LLM в DB не пишет); невалидное поле → None
# (план не инвалидируется — поле аддитивное).
FUTURE_INTENT_KINDS = ("follow_up", "open_dispute")
FUTURE_INTENT_GOAL_MAX = 200


@dataclass
class FutureIntent:
    """Валидированное будущее намерение (ASAP 8 F6 §13.1).

    ``kind`` — закрытый список (follow_up/open_dispute); ``goal`` — короткий
    текст-цель ≤200 (сервис повторно канонизирует через mca_intents.canon_text,
    R17). Создание записи — только сервисом-продюсером, не LLM."""

    kind: str
    goal: str

DEFAULT_DIRECT_L1_EVIDENCE_MAX_CHARS = 4000

# §1.5: force/direct-address факты (детерминированные, LLM их не решает).
# FIX-CORRECTIVE-R1 (21.10.2026, P2): autonomous-строка называет блок с
# предыдущими ответами бота и явное равноправие silent/react (без новых
# механизмов — только текст существующего факта).
FORCE_LINE = "прямое обращение к боту: текстовый ответ обязателен"
AUTONOMOUS_LINE = ("автономный контекст (ответ на сообщение бота): действие "
                   "свободное; твой предыдущий ответ - в блоке ОТВЕТЫ БОТА, "
                   "если он есть; молчание и реакция - равноправные исходы")

# FIX-CORRECTIVE-R1 (P2): заголовок секции недавних ответов бота в L1-контексте
# (тексты берутся из существующей таблицы bot_replies, вызывающий передаёт).
BOT_REPLIES_SECTION = "ОТВЕТЫ БОТА (недавние)"

# L1D (22.10.2026, директива владельца plans/features/owner-corrective-
# initreply-2026-10-22.md §1-2): условия ИНИЦИАТИВНОГО L1. Формы участия
# равноправны (reply не предпочтительнее обычного сообщения; молчание -
# полноценный исход); повод Observer - предложение для решения, а не приказ.
# Только текст существующего факта, без новых механизмов.
INITIATIVE_LINE = ("автономная инициатива (никто бота не звал): действие "
                   "свободное - написать в чат обычным сообщением, ответить "
                   "как Telegram-reply на конкретное сообщение (id из окна "
                   "[msg:N]), поставить реакцию или промолчать; никакая форма "
                   "не имеет приоритета; reply уместен только к сообщению "
                   "своего смыслового адресата, иначе - обычное сообщение; "
                   "повод наблюдателя - предложение, а не приказ")

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
    future_intent: "FutureIntent | None" = None  # F6 §13.1 (allowlisted)
    # ASAP 8 v6 (D04 §18C.7): execution mode (closed set; normalized).
    execution_mode: str = "none"
    execution_mode_source: str = "derived"   # derived | llm
    # SOUL-1 (W3, SOUL-05.1): ровно один необязательный совет по приёму юмора.
    comic_strategy: str = "none"
    # ── L1D (22.10.2026, директива владельца §3): форма участия — РЕШЕНИЕ L1,
    # не транспорта. ``delivery`` — Telegram-доставка текста ("chat"|"reply"|""),
    # ``target_message_id`` — конкретное сообщение из контекста ([msg:N],
    # smart_messages.id), выбранное LLM для reply/реакции; ``target_user_id`` —
    # СМЫСЛОВОЙ адресат (сам по себе reply НЕ включает — §3 директивы).
    # Нормализация: мусор → дефолты (""/None); отсутствие полей ≠ reply.
    delivery: str = ""
    target_message_id: int | None = None
    target_user_id: int | None = None

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
        rich-gate, media_writer_needed. Никогда не бросает.

        SOUL-1 (W3, SOUL-05.2): ``one_word`` переносится ЗНАЧЕНИЕМ (не алиас
        ``micro``): это два разных действующих extent со своими блоками и
        валидаторами. Схлопывание в ``micro`` теряло строгий контракт «ровно
        одно лексическое слово» (SOUL-AMD.1.6)."""
        from services import response_extent as _extent

        extent = self.effective_extent()
        if extent in _extent.EXTENTS:
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
            comic_strategy=self.comic_strategy if self.comic_strategy in
            COMIC_STRATEGIES else "none",
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


def _optional_positive_int(value) -> int | None:
    """L1D: необязательный id из плана (мусор/bool/≤0 → None). Не бросает."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def reply_binding_requested(plan) -> bool:
    """L1D (директива 22.10 §3): план просит Telegram-reply доставку.

    Ровно одно сочетание включает привязку: action=reply И delivery=reply И
    выбран конкретный target_message_id. target_user_id сам по себе reply
    НЕ включает (сценарий C — обращение без reply). Пустое/старое поле
    delivery → обычное сообщение (отсутствие решения ≠ reply)."""
    try:
        return (getattr(plan, "action", "") == "reply"
                and getattr(plan, "delivery", "") == "reply"
                and bool(getattr(plan, "target_message_id", None)))
    except Exception:      # pragma: no cover - защитная ветка
        return False


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
    # ── ASAP 2 Direct Chat (§3.2 source-2026-10-22.md, 23.10.2026): строгий
    # JSON boolean. Только реальный true → True; «false»/null/«true»-строка/
    # список/объект → False (не запрос уточнения). Безопасный fallback
    # прежний, нового LLM-вызова ради исправления типа нет.
    plan.needs_clarification = data.get("needs_clarification") is True
    # ── SOUL-1 (W3, SOUL-05.1): ровно один необязательный comic_strategy.
    # Закрытый набор; невалидное/отсутствующее → "none" (совет, не приказ).
    plan.comic_strategy = _closed(data.get("comic_strategy"), COMIC_STRATEGIES,
                                  "none")
    # ── ASAP 8 v6 (D04 §18C.7): execution_mode. Явное значение от LLM
    # (allowlisted аддитивное поле, прецедент future_intent); невалидное/
    # отсутствующее → дет. деривация из capabilities. Никогда не тихо:
    # источник значения фиксируется в плане.
    requested_mode = str(data.get("execution_mode") or "").strip().lower()
    if requested_mode in EXECUTION_MODES:
        plan.execution_mode = requested_mode
        plan.execution_mode_source = "llm"
    else:
        plan.execution_mode = derive_execution_mode(plan.capabilities_needed)
        plan.execution_mode_source = "derived"
    # ── L1D (22.10.2026): форма участия. Невалидное/отсутствующее delivery →
    # "" (обычное сообщение); id — только положительные целые.
    plan.delivery = _closed(data.get("delivery"), L1_DELIVERY_MODES, "")
    plan.target_message_id = _optional_positive_int(
        data.get("target_message_id"))
    plan.target_user_id = _optional_positive_int(data.get("target_user_id"))
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
    # ── ASAP 8 (F6 §13.1): allowlisted future_intent. Схема строго
    # валидируется; невалидное поле → None (план остаётся валидным).
    fi = data.get("future_intent")
    if isinstance(fi, dict):
        fi_kind = str(fi.get("kind") or "").strip().lower()
        fi_goal = fi.get("goal")
        fi_goal_text = fi_goal.strip() if isinstance(fi_goal, str) else ""
        if fi_kind in FUTURE_INTENT_KINDS and fi_goal_text:
            plan.future_intent = FutureIntent(
                kind=fi_kind, goal=fi_goal_text[:FUTURE_INTENT_GOAL_MAX])
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
                             max_output_tokens=None, timeout_seconds=None,
                             temperature=None):
    """Выделенный слот §1.6 через существующий транзитный канал LLMClient.

    Контракт (прецедент ``summary_l1_clusterizer._dedicated_generate``):
    per-call ``base_url``/``model``/``api_key`` через ``_post`` — тот же
    retry/fallback-канал без подмены на глобальную модель. Возврат
    ``(content, usage)``. Ошибки (LLMError/TimeoutError) — вызывающему
    (ladder §1.6).

    ASAP 8 v6 (D03, §18C.6): ``temperature`` — сохранённая температура
    L1 РЕАЛЬНО применяется в payload (None → ключ не добавляется, дефолт
    провайдера). Авторизация ключа/бюджета — вне этой функции (см.
    :func:`authorize_l1_call`): транспорт остаётся на слоте, а permission
    policy — общая с обычными вызовами."""
    import asyncio

    payload: dict = {"model": slot.model, "messages": messages}
    if temperature is not None:
        payload["temperature"] = float(temperature)
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


async def authorize_l1_call(llm, chat_id: int | None) -> str:
    """D03 (§18C.1): та же permission-политика ключей/бюджета, что у
    обычных LLM-вызовов — ПЕРЕД каждым paid/dedicated L1 attempt.

    Реюз ``LLMClient._resolve_api_key_and_source(chat_id)``: no-own-key +
    global-forbidden → NoApiKeyForChat('forbidden'); exhausted budget →
    NoApiKeyForChat('budget'); own chat key → 'chat'; иначе 'global'
    (fail-open контракт клиента сохранён внутри резолвера). Метода нет
    (тестовые LLM) → 'global'. Возврат — source, определяющий БЮДЖЕТНЫЙ
    учёт попытки; transport-ключ dedicated-слота остаётся slot.api_key.
    NoApiKeyForChat/LLMError — проброс вызывающему (блок попытки)."""
    resolver = getattr(llm, "_resolve_api_key_and_source", None)
    if resolver is None:
        return "global"
    _key, source = await resolver(chat_id)
    return str(source or "global")


async def record_l1_usage(llm, *, usage, messages, content, model: str,
                          chat_id: int | None, correlation_id: str | None,
                          credential_source: str = "global") -> None:
    """D03 (§18C.1): учёт КАЖДОЙ попытки (первая + repair) — usage-row
    (usage/cost/unknown-cost) + бюджетный счётчик глобального ключа
    (mirror ``_record_global_usage``: только source='global'; свой ключ
    чата бюджет НЕ тратит). Fail-open. Никогда не бросает."""
    try:
        from services import usage_events as _ue
        in_toks, out_toks, estimated = _ue.resolve_token_counts(
            usage, messages, content)
        await _ue.record(
            getattr(llm, "_pg", lambda: None)(),
            module="direct_chat", step="l1_planner",
            correlation_id=correlation_id, chat_id=chat_id, model=model,
            input_tokens=in_toks, output_tokens=out_toks,
            tokens_estimated=estimated,
            source=_ue.normalize_source(
                "chat" if credential_source == "chat" else "global"))
    except Exception:
        pass
    try:
        if credential_source != "global" or chat_id is None:
            return
        from services import chat_usage
        pg = getattr(llm, "_pg", lambda: None)()
        await chat_usage.report_call(
            pg, chat_id, chat_usage.estimate_tokens(content))
    except Exception:
        pass


# ── §1.5: компактный L1-контекст ────────────────────────────────────────────

L1_WINDOW_MESSAGES = 20       # §1.5: окно последних N (дефолт 20)
L1_PERSONA_FRAME_CHARS = 400  # голова character_block
L1_REPLY_BLOCK_CHARS = 400
L1_WINDOW_LINE_CHARS = 200

# ASAP2 T10-BOUNDARY / CLAR-CTX-HONEST (§6.1 #10, §3.4, §3.5 source):
# единственная честная пометка о том, что видна не вся история. Факт берётся
# у самого кода (усечение вызовом/лимитом окна/`_cap_context`), анализаторов
# и порогов нет. В ответе канон L2 (chat_prompts.py:515/:521) велит называть
# границу знания обычными словами и не публиковать служебные метки.
HISTORY_SCOPE_SECTION = "ГРАНИЦА ИСТОРИИ"
HISTORY_PARTIAL_LINE = (
    "показана только часть истории чата: более ранние сообщения в этот "
    "пакет не переданы")
#: Та же пометка для строки-анонса L2 (Global_Context): "... (…)".
HISTORY_PARTIAL_INLINE = "более ранняя история не передана"


def build_l1_context(*, query, current_question: str = "",
                     reply_block: str = "", window=None,
                     speaker: str = "", addressee: str = "",
                     memory_hints: str = "", speech_hints: str = "",
                     capabilities=(), force_line: str = "",
                     persona_frame: str = "",
                     bot_replies: tuple[str, ...] = (),
                     budget_tokens: int | None = None,
                     with_ids: bool = False,
                     alias_resolver=None,
                     history_partial: bool = False) -> str:
    """§1.5: compact-пакет L1. Полный Writer-контекст L1 НЕ получает.
    Кап бюджета ``limits.direct_l1_context_tokens`` (дефолт 1600):
    дет. деградация — сначала сокращается окно (заголовки/сообщение/
    участники неприкосновенны), затем hint-секции, затем жёсткий кап.
    FIX-CORRECTIVE-R1 (P2): ``bot_replies`` — недавние ответы бота
    (существующая таблица bot_replies; вызывающий решает, сколько давать);
    секция даёт планеру собственную предыдущую реплику — критерий
    «разговор уже завершён» из правила 3 канона. Никогда не бросает.
    ASAP2 T10-BOUNDARY: ``history_partial`` — вызывающий знает, что в БД
    есть сообщения старше видимого окна; пометка ``ГРАНИЦА ИСТОРИИ``
    добавляется ровно по факту усечения (флаг или окно > L1_WINDOW_MESSAGES
    либо срез ``_cap_context``) и переживает сжатие бюджета."""
    try:
        sections: list[tuple[str, str]] = []
        current = str(current_question or query or "").strip()
        if current:
            sections.append(("СООБЩЕНИЕ", current))
        if str(reply_block or "").strip():
            sections.append(("ОТВЕТ НА (reply/цитата)",
                             str(reply_block).strip()[:L1_REPLY_BLOCK_CHARS]))
        bot_lines = [str(line or "").strip()[:L1_REPLY_BLOCK_CHARS]
                     for line in (bot_replies or ())]
        bot_lines = [line for line in bot_lines if line][:3]
        if bot_lines:
            sections.append((BOT_REPLIES_SECTION, "\n".join(bot_lines)))
        window_lines = render_window_lines(window, L1_WINDOW_MESSAGES,
                                           with_ids=with_ids,
                                           alias_resolver=alias_resolver)
        if window_lines:
            sections.append(("ПОСЛЕДНИЕ СООБЩЕНИЯ", "\n".join(window_lines)))
        # ASAP2 T10-BOUNDARY: пометка ставится ровно по факту усечения —
        # вызывающий сказал «в БД есть более ранние сообщения»
        # (`history_partial`) ИЛИ окно не влезло в L1_WINDOW_MESSAGES.
        if bool(history_partial) or len(tuple(window or ())) > L1_WINDOW_MESSAGES:
            sections.append((HISTORY_SCOPE_SECTION, HISTORY_PARTIAL_LINE))
        speaker = str(speaker or "неизвестно").strip()
        addressee = str(addressee or "чат").strip()
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
    """Структурный кап §1.5 + §18C.5: защита СТРУКТУРНЫХ блоков
    (СООБЩЕНИЕ/УЧАСТНИКИ/ДОСТУПНЫЕ ВОЗМОЖНОСТИ/УСЛОВИЯ — вопрос, machine
    contract, direct-address metadata), окно/hints сжимаются первыми
    (10 → 5 → 0), СООБЩЕНИЕ при переполнении сохраняет head+tail (хвост
    вопроса НЕ теряется), финальная сборка верифицируется tokenizer'ом.
    Остаточное переполнение режет КРУПНЕЙШИЙ незащищённый блок, не хвост
    пакета. Никогда не бросает."""
    try:
        from services.token_counter import count_tokens
        if count_tokens(text) <= budget:
            return text
        protected = {"СООБЩЕНИЕ", "УЧАСТНИКИ", "ДОСТУПНЫЕ ВОЗМОЖНОСТИ",
                     "УСЛОВИЯ", HISTORY_SCOPE_SECTION}

        def _render(pairs) -> str:
            return "\n\n".join(f"[{name}]\n{body}" for name, body in pairs)

        pairs: list[tuple[str, str]] = list(sections_budget)
        # Шаг 1: окно сокращается первым (10 → 5 → 0 строк).
        for window_cap in (10, 5, 0):
            rebuilt = []
            _has_note = any(n == HISTORY_SCOPE_SECTION for n, _ in pairs)
            for name, body in pairs:
                if name == "ПОСЛЕДНИЕ СООБЩЕНИЯ":
                    lines = body.splitlines()
                    kept = lines[-window_cap:] if window_cap else []
                    # T10-BOUNDARY: строки реально отброшены — факт, а не
                    # эвристика; пометка переживает дальнейшее сжатие
                    # (protected) и встаёт на место окна, если оно ушло всё.
                    dropped = len(kept) < len(lines)
                    if kept:
                        rebuilt.append((name, "\n".join(kept)))
                    if dropped and not _has_note:
                        rebuilt.append((HISTORY_SCOPE_SECTION,
                                        HISTORY_PARTIAL_LINE))
                    continue
                rebuilt.append((name, body))
            pairs = rebuilt
            if count_tokens(_render(pairs)) <= budget:
                return _render(pairs)
        # Шаг 2: незащищённые hint-секции сжимаются пропорционально,
        # пока пакет не влезет (защищённые неприкосновенны).
        def _shrink_hints(pairs, factor: float):
            out = []
            for name, body in pairs:
                if name in protected or not body:
                    out.append((name, body))
                    continue
                keep = max(80, int(len(body) * factor))
                out.append((name, body[:keep]))
            return out

        for factor in (0.6, 0.3, 0.1):
            pairs = _shrink_hints(pairs, factor)
            if count_tokens(_render(pairs)) <= budget:
                return _render(pairs)
        # Шаг 3: СООБЩЕНИЕ переполняет само → head+tail (хвост вопроса
        # сохраняется; §18C.5 «никогда не резать семантический хвост»).
        rebuilt = []
        for name, body in pairs:
            if name == "СООБЩЕНИЕ" and count_tokens(body) > max(
                    200, budget // 3):
                chars = max(400, budget // 2)
                body = (body[:int(chars * 0.6)]
                        + "\n[…сообщение обрезано под бюджет]\n"
                        + body[-int(chars * 0.4):])
            rebuilt.append((name, body))
        pairs = rebuilt
        # Шаг 4: остаточное переполнение — режем КРУПНЕЙШИЙ незащищённый
        # блок (структурные блоки и хвост вопроса не страдают).
        while count_tokens(_render(pairs)) > budget:
            victim = None
            victim_tokens = 0
            for name, body in pairs:
                if name in protected or not body:
                    continue
                tokens = count_tokens(body)
                if tokens > victim_tokens:
                    victim, victim_tokens = name, tokens
            if victim is None:
                break
            rebuilt = []
            for name, body in pairs:
                if name == victim:
                    # Прогресс обязателен: блок ≤80 симв. уже не режется
                    # (пол = 80 в шаге 2), поэтому при нехватке бюджета он
                    # убирается целиком — иначе цикл не завершается.
                    half = len(body) // 2
                    body = body[:half] if half >= 80 else ""
                rebuilt.append((name, body))
            pairs = rebuilt
        return _render(pairs)
    except Exception:          # pragma: no cover - защитная ветка
        return text


def render_window_lines(window, limit: int = L1_WINDOW_MESSAGES, *,
                        with_ids: bool = False, alias_resolver=None) -> list[str]:
    """§1.5: последние N сообщений окна → компактные строки
    ``имя: текст`` (кап на строку). Никогда не бросает.

    L1D (22.10.2026, директива §2): ``with_ids=True`` — разметка окна
    идентификаторами и reply-связями (``[msg:ID] [user:UID] имя: текст
    (ответ на msg:N)``) — L1 выбирает цель reply/реакции ИЗ КОНТЕКСТА сама
    (та же конвенция разметки, что у окна наблюдателя). Прямой L1 (Direct)
    продолжает получать прежний формат (with_ids=False по умолчанию).

    ASAP 3 Corrective §4.2: ``alias_resolver`` — действующий per-chat
    резолвер; отображаемое имя строки резолвится по известному user_id
    (история/``author_name`` не переписываются). Без резолвера — прежний
    формат (обратная совместимость тестов/вызовов)."""
    lines: list[str] = []
    try:
        rows = [r for r in (window or []) if isinstance(r, dict)]
        for row in rows[-max(0, int(limit)):]:
            raw_author = str(row.get("author_name") or "").strip()
            author = raw_author or "?"
            try:
                row_uid = row.get("user_id")
                row_uid = int(row_uid) if row_uid is not None else None
            except (TypeError, ValueError):
                row_uid = None
            if alias_resolver is not None and row_uid is not None:
                try:
                    author = str(alias_resolver.resolve(
                        row_uid, raw_author or None, None))
                except Exception:      # pragma: no cover - fail-open рендера
                    author = raw_author or "?"
            body = _WS_RE.sub(" ", str(row.get("text") or "")).strip()
            if not body:
                media = str(row.get("media_type") or "").strip()
                body = f"[{media}]" if media else "[медиа]"
            prefix = ""
            reply_mark = ""
            if with_ids:
                msg_id = row.get("id")
                try:
                    msg_id = int(msg_id) if msg_id is not None else None
                except (TypeError, ValueError):
                    msg_id = None
                user_id = row_uid
                if msg_id is not None:
                    prefix = f"[msg:{msg_id}] "
                if user_id is not None:
                    prefix += f"[user:{user_id}] "
                reply_to = row.get("reply_to_id")
                if reply_to not in (None, "", 0, "0"):
                    try:
                        reply_mark = f" (ответ на msg:{int(reply_to)})"
                    except (TypeError, ValueError):
                        reply_mark = ""
            lines.append(f"{prefix}{author}: {body[:L1_WINDOW_LINE_CHARS]}"
                         f"{reply_mark}")
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
    """§1.2 → §18C.2 (D04): обёртка совместимости над fair-allocation
    evidence pack (services.direct_execution.build_evidence_pack) —
    per-source резервирование, identity/limitations, честные пометки
    «не доставлено». Legacy-сигнатура (строка) сохранена для вызовов вне
    L1-пайплайна. Никогда не бросает; пустой пакет → ""."""
    try:
        from services.direct_execution import build_evidence_pack
        pack = build_evidence_pack(raw, plan, capacity_chars=max_chars)
        return pack.text
    except Exception:          # pragma: no cover - защитная ветка
        return ""


# ── §1.1: plan-блок для L2 Writer ───────────────────────────────────────────


def _renders_extent_block(plan) -> bool:
    """Станет ли ``render_extent_block`` НЕПУСТЫМ в фактическом payload.

    Extent-блок плана ЗАМЕНЯЕТ ``MODE_*_BLOCK``
    (``prompt_style_blocks.resolve_mode_parts``), поэтому только непустой
    блок снимает режимный текст анализа. Проверка идёт тем же рендерером и
    по тому же ``ResponsePlan``, который видит L2 Writer
    (``L1Plan.to_response_plan``). Никогда не бросает.
    """
    try:
        if plan is None:
            return False
        from services import response_extent as _extent
        response_plan = (plan.to_response_plan()
                         if hasattr(plan, "to_response_plan") else plan)
        return bool(_extent.render_extent_block(response_plan))
    except Exception:      # pragma: no cover - защитная ветка
        return False


def analysis_directive_needed(plan, response_mode: str = "",
                              modes_on: bool = True) -> bool:
    """Нужна ли точная analysis-директива в plan-блоке L2.

    SPEECH-P0-CORE-SERIOUS (25.10.2026, §1 аддендума): серьёзный разбор
    (``response_act=research``) получает дословную инструкцию анализа/Writer
    в ``<Response_Plan>``, если режимный блок её в payload не несёт.

    Для ``deep_research`` это решает extent-блок, а не имя режима
    (SPEECH-P0-DEEP-PAYLOAD, ревью 25.10.2026): непустой extent-блок
    (``extent``/``form_override`` вне ``auto``) заменяет
    ``MODE_DEEP_RESEARCH_BLOCK`` целиком — значит тексты нужны в плане;
    при пустом extent режимный блок рендерится и остаётся единственным
    носителем (дубля нет). Режимы OFF → режимного блока нет вовсе → True.
    Принимает ``L1Plan`` (``response_act``) или ``ResponsePlan``
    (``task_kind``). Никогда не бросает.
    """
    try:
        if plan is None:
            return False
        mode = str(response_mode or "") or plan_response_mode(plan)
        if mode == "deep_research" and bool(modes_on):
            # Режимный блок заменяется непустым extent-блоком: тогда те же
            # дословные тексты обязан нести plan-блок (ровно один раз).
            return _renders_extent_block(plan)
        act = str(getattr(plan, "response_act", "") or "")
        kind = str(getattr(plan, "task_kind", "") or "")
        return act == "research" or kind == "research"
    except Exception:      # pragma: no cover - защитная ветка
        return False


def build_l2_plan_block(plan: L1Plan | None, *, rejected=(),
                        clarification: bool = False,
                        low_confidence: bool = False,
                        include_delivery: bool = False,
                        include_analysis: bool = False) -> str:
    """Hint-блок плана для L2 Writer (system/user данные, БЕЗ механического
    штампа: §2.4 ТЗ — L2 видит plan как hint-строку). Языковая дисциплина
    D11: без «коротко»/«по делу». Никогда не бросает.

    L1D (22.10.2026, директива §2): ``include_delivery=True`` (инициативный
    Writer) доводит до Writer ВЫБРАННУЮ L1 форму участия — прямой ответ на
    сообщение / обращение к человеку без reply / самостоятельная реплика,
    чтобы текст соответствовал способу доставки. Прямой чат (Direct) форму
    доставки плана не получает (контракт Direct не менялся).

    SPEECH-P0-CORE-SERIOUS (25.10.2026, §1 аддендума): ``include_analysis``
    добавляет в план дословные ``ANALYSIS_DIRECTIVE_TEXT``/``
    ANALYSIS_WRITER_TEXT`` для serious-разбора (внутренний анализ не
    пересказывается, глубина не задаёт длину ответа). Флаг выставляет
    вызывающий по ``analysis_directive_needed``: у deep_research тексты уже
    в режимном блоке, но только пока его не заменил extent-блок плана
    (SPEECH-P0-DEEP-PAYLOAD), — предикат учитывает это сам."""
    try:
        if plan is None:
            return ""
        lines: list[str] = ["<Response_Plan>",
                            f"действие: {str(plan.action or 'reply')}"]
        act = str(plan.response_act or "other")
        # ASAP 2 (B1 review-struct 23.10.2026; §3.2 source-2026-10-22.md):
        # сама строка «смысловой акт ответа: clarification» — тоже
        # model-facing сигнал уточнения. Она допустима только при реально
        # валидном уточнении (строгий needs_clarification=true И непустой
        # clarification_target); в невалидной ветке строки нет вовсе, иначе
        # L2 получает второй приказ переспросить вопреки плану.
        target = str(getattr(plan, "clarification_target", "") or "").strip()
        act_ok = (act != "clarification"
                  or (bool(clarification)
                      and getattr(plan, "needs_clarification", False) is True
                      and bool(target)))
        if act and act != "other" and act_ok:
            lines.append(f"смысловой акт ответа: {act}")
        tone = str(plan.tone or "inherit")
        if tone and tone != "inherit":
            lines.append(f"тон: {tone}")
        mirroring = str(plan.emotional_mirroring or "none")
        if mirroring and mirroring != "none":
            lines.append(f"зеркалирование эмоций собеседника: {mirroring}")
        strategy = str(getattr(plan, "comic_strategy", "") or "none")
        if strategy and strategy != "none":
            # SOUL-05.1: совет L2, а не приказ быть смешным.
            lines.append(f"если уместно, приём юмора: {strategy}")
        if include_delivery:
            # L1D: форма участия выбрана L1; Writer не меняет адресата/способ.
            delivery = str(getattr(plan, "delivery", "") or "")
            target_id = getattr(plan, "target_message_id", None)
            target_user = getattr(plan, "target_user_id", None)
            if delivery == "reply" and target_id:
                lines.append(f"форма доставки: Telegram-reply на сообщение "
                             f"[msg:{target_id}] - текст должен быть прямым "
                             f"ответом именно на это сообщение")
            elif target_user:
                lines.append(f"смысловой адресат: [user:{target_user}] - "
                             f"обратись к нему в тексте; технической "
                             f"reply-привязки у реплики нет")
            else:
                lines.append("форма доставки: самостоятельная реплика в чат, "
                             "без reply-привязки")
        note = rejected_note(rejected)
        if note:
            lines.append(note)
        # ── SPEECH-P0-CORE-SERIOUS (25.10.2026, §1 аддендума): дословные
        # тексты анализа/Writer в plan-блоке для serious-разбора. Один
        # источник (`prompt_style_blocks`), deep-режим их уже несёт.
        if include_analysis:
            try:
                from services import prompt_style_blocks as _psb
                _directive = str(_psb.ANALYSIS_DIRECTIVE_TEXT or "").strip()
                _writer = str(_psb.ANALYSIS_WRITER_TEXT or "").strip()
            except Exception:      # pragma: no cover - защитная ветка
                _directive = _writer = ""
            if _directive:
                lines.append(f"как разбирать: {_directive}")
            if _writer:
                lines.append(f"как подать разбор: {_writer}")
        if low_confidence:
            lines.append("уверенность плана низкая: опирайся на контекст "
                         "разговора, а не на подсказки плана.")
        # ── ASAP 2 Direct Chat (§4.3 source-2026-10-22.md, 23.10.2026):
        # старый императив «Ничего кроме вопроса не пиши» заменён узкой
        # фразой владельца; директива передаётся ТОЛЬКО от корректного
        # финального поля L1 (needs_clarification=true + непустой
        # clarification_target). Пустая цель → общей директивы «уточни
        # что-нибудь» нет (generic-опрос не генерируется, §3.2).
        if clarification:
            if target:
                lines.append(f"недостающий обязательный предмет: {target}")
                lines.append(
                    "Для выполнения этого запроса действительно не хватает "
                    "обязательного предмета, указанного в плане уточнения. "
                    "Спроси только о нём одним понятным вопросом. Не "
                    "предлагай человеку выбирать необязательные варианты "
                    "формата, объёма, интервала или способа объяснения. "
                    "После ответа следует продолжить исходную задачу.")
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

# §18C.3: planner failure не стирает required tools — дет. inference
# required capability из текста запроса (высокая точность: только явные
# URL и явные search-маркеры).
_FALLBACK_SEARCH_RE = re.compile(
    r"поищи|поиск\w*|найди|найти|загугли|погугли|в интернете|в сети|"
    r"проверь (в )?интернет|search", re.IGNORECASE)


def infer_fallback_capabilities(query: str, reply_text: str = "",
                                *, announced=()) -> tuple[str, ...]:
    """§18C.3: безопасный дет. capability-резолвер для fallback-плана.
    URL (в запросе/реплае) → fetch_url; явный search-маркер → web_search.
    Только capability с активным инструментом; пусто → (). Никогда не
    бросает."""
    try:
        active = {str(t or "").strip() for t in (announced or ())}
        caps: list[str] = []
        text = f"{query or ''}\n{reply_text or ''}"
        try:
            from services.smartmodule_urls import extract_urls
            if extract_urls(text) and "fetch_article" in active:
                caps.append("fetch_url")
        except Exception:
            pass
        if _FALLBACK_SEARCH_RE.search(str(query or "")) \
                and "execute_web_search" in active:
            caps.append("web_search")
        return tuple(caps)
    except Exception:      # pragma: no cover - защитная ветка
        return ()


def fallback_plan(query, *, action: str = "reply",
                  allowed_actions=("REPLY",),
                  capabilities_needed: tuple[str, ...] = ()) -> L1Plan:
    """Deterministic safe fallback (§1.6 + §18C.3): classify_request +
    прежняя demote-матрица (action задаёт вызывающий из pre_action).
    L1Plan с ``source="fallback"``; capabilities — дет. inference
    required-инструментов (вызывающий передаёт
    ``infer_fallback_capabilities(...)``): planner outage больше НЕ
    удаляет search/fetch молча. execution_mode — деривация от
    capabilities."""
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
    caps = tuple(str(c) for c in (capabilities_needed or ()) if str(c))
    plan = L1Plan(
        action=act,
        response_act="other",
        extent=extent,
        structure=legacy.structure,
        delivery_hint=legacy.delivery_hint if legacy.delivery_hint in
        L1_DELIVERY else "plain",
        tool_policy=legacy.tool_policy if legacy.tool_policy in
        L1_TOOL_POLICIES else "none",
        capabilities_needed=caps,
        confidence=0.0,
        confidence_bucket="low",
        source="fallback")
    plan.execution_mode = derive_execution_mode(caps)
    plan.execution_mode_source = "derived"
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


# ── ASAP 8 v6 (D03/D04): process-local diagnostics (Inspector) ───────────────
# Только числа/коды (R17: без секретов/приватных текстов); последний прогон
# на чат. Читатель — GET /api/direct/context-diagnostics (аддитивное поле).

_L1_DIAG_MAX_CHATS = 256
_l1_diagnostics: dict[int, dict] = {}


def record_l1_diagnostics(chat_id: int | None, **fields) -> None:
    """Запомнить R17-safe оси последнего L1-прогона чата (fail-open).
    Допускаются только числа/bool/короткие ident-строки."""
    try:
        if chat_id is None:
            return
        safe: dict = {"ts": int(time.time())}
        for key, value in (fields or {}).items():
            if value is None:
                continue
            if isinstance(value, bool) or isinstance(value, (int, float)):
                safe[key] = value
            elif isinstance(value, str):
                candidate = value.strip()
                if candidate and len(candidate) <= 64 \
                        and not any(ch.isspace() for ch in candidate):
                    safe[key] = candidate
        _l1_diagnostics[int(chat_id)] = safe
        if len(_l1_diagnostics) > _L1_DIAG_MAX_CHATS:
            try:
                oldest = min(_l1_diagnostics,
                             key=lambda c: _l1_diagnostics[c].get("ts", 0))
                _l1_diagnostics.pop(oldest, None)
            except Exception:
                _l1_diagnostics.clear()
    except Exception:          # pragma: no cover - fail-open
        pass


def get_l1_diagnostics(chat_id: int | None) -> dict | None:
    """Последний снапшот L1-прогона чата (или None). Fail-open."""
    try:
        if chat_id is None:
            return None
        return dict(_l1_diagnostics.get(int(chat_id)) or None) or None
    except Exception:      # pragma: no cover - fail-open
        return None


__all__ = [
    "ACTIONS", "L1_EXTENTS", "LONGFORM_L1_EXTENTS", "L1Plan", "L1ModelSlot",
    "FutureIntent", "FUTURE_INTENT_KINDS", "FUTURE_INTENT_GOAL_MAX",
    "FORCE_LINE", "AUTONOMOUS_LINE", "INITIATIVE_LINE", "REPAIR_ANNOTATION",
    "L1_DELIVERY_MODES", "EXECUTION_MODES", "normalize_l1_plan",
    "parse_l1_plan", "reply_binding_requested",
    "build_repair_messages", "confidence_bucket", "direct_l1_enabled",
    "l1_fallback_enabled", "l1_context_tokens", "l1_timeout_seconds",
    "l1_max_output_tokens", "l1_temperature", "resolve_l1_model",
    "dedicated_generate", "authorize_l1_call", "record_l1_usage",
    "infer_fallback_capabilities", "build_l1_context", "render_window_lines",
    "build_evidence_packet", "fallback_plan", "plan_response_mode",
    "emit_l1_plan_event", "build_l2_plan_block",
    "analysis_directive_needed", "rejected_note",
    "derive_execution_mode", "record_l1_diagnostics", "get_l1_diagnostics",
]
