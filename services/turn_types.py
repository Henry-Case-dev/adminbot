"""UNIFIED-REPLY UR-A (arch contract §2): фрозен-контракты одного хода.

Модуль — ТОЛЬКО структуры данных (датаклассы/enums + неизменяемая таблица
политик). Здесь нет ни исполнения, ни второго пайплайна: вход/движок живут в
`services/direct_chat_service.py` (`_execute_turn`), политика L1 —
`services/direct_l1.py`, сборка контекста — `direct_context_composer.py`,
инструменты — `direct_execution.py`.

Карта пяти контрактов §2 (что где определено):

* §2.1 `TurnRequest` — здесь (владелец: адаптеры входа, consumer: движок);
* §2.2 `ContextSelection`/`ContextFragment`/`SelectionProvenance` — уже
  определены владельцем `services/direct_context_composer.py` (UR-C, слито);
  второй копии здесь нет намеренно: два конкурирующих типа одного контракта
  разошлись бы по семантике;
* §2.3 `ToolEvidence`/`SourceRecord` — владелец `services/direct_execution.py`
  (UR-B, слито);
* §2.4 `L1Plan` — владелец `services/direct_l1.py` (расширяется на месте);
* §2.5 `LLMCompletion` — владелец `services/llm_client.py` (UR-D).

`time_snapshot` (§3, ChatClock) отдаётся Time-lane: тип импортируется только
для проверяющих типов и не создаёт рантайм-зависимости от ещё не слитого
модуля.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:       # pragma: no cover - только для статической проверки
    from services.chat_clock import TimeSnapshot


# ── §2.1: типы хода ─────────────────────────────────────────────────────────

class TurnType(str, Enum):
    """Тип хода. Один движок, два триггера (UR-RES-01/UR-01.1)."""

    DIRECT = "direct"
    INITIATIVE = "initiative"


@dataclass(frozen=True)
class TurnPolicy:
    """Резолв типа хода: слот, схема плана, repair, учёт (UR-02.x).

    Поля описывают ОДИН код исполнения L1. Две строки таблицы различаются
    только правом на молчание при блокировке политики ключей/бюджета
    (`silent_on_policy_block`) — это «право говорить», а не отдельный L1.
    """

    turn_type: str = TurnType.DIRECT.value
    plan_schema: str = "l1_plan_v2"
    slot_policy: str = "l1_slot_then_main_fallback"
    repair_policy: str = "json_bounded_1"
    temperature_source: str = "limits.direct_l1_temperature"
    usage_accounting: str = "l1_planner"
    silent_on_policy_block: bool = False


#: Таблица политик — чистые данные контракта (UR-02.2): схема плана, repair и
#: учёт usage одинаковы; различие — только право молчания при блоке политики.
TURN_POLICIES: Mapping[str, TurnPolicy] = {
    TurnType.DIRECT.value: TurnPolicy(
        turn_type=TurnType.DIRECT.value, silent_on_policy_block=False),
    TurnType.INITIATIVE.value: TurnPolicy(
        turn_type=TurnType.INITIATIVE.value, silent_on_policy_block=True),
}


def resolve_turn_type(trigger_type) -> str:
    """Нормализация trigger_type → TurnType.value. Никогда не бросает."""
    value = str(getattr(trigger_type, "value", trigger_type) or "").strip()
    return value if value in TURN_POLICIES else TurnType.DIRECT.value


def turn_policy(trigger_type) -> TurnPolicy:
    """Политика хода по trigger_type (по умолчанию — прямой ход)."""
    return TURN_POLICIES[resolve_turn_type(trigger_type)]


@dataclass(frozen=True)
class ReplyParentRef:
    """Reply/quote-родитель хода (P0-источник, §2.2)."""

    tg_id: int | None = None
    author_uid: int | None = None
    alias: str = ""
    source_ref: str = ""


@dataclass(frozen=True)
class AddresseeRef:
    """Смысловой адресат хода (для инициативы — addressee_user_id)."""

    user_id: int | None = None
    label: str = "чат"
    source: str = "chat"        # chat | bundle | observer


@dataclass(frozen=True)
class OpportunityRef:
    """Повод инициативного хода: durable intent либо эфемерный observer."""

    intent_id: int | None = None
    goal: str = ""
    kind: str = ""
    origin: str = ""
    created_at: int | None = None
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class SlotBudgetMeta:
    """Результат резолва слота/бюджета L1 (§1.6 + ER-08) ДО планирования.

    ``credential_source`` — итог одного permission-резолва (D03, UR-02.1);
    модель, фактически планировавшая ход, видна на трассе (`slot`/`model`).
    """

    slot: str = "main"                 # main | l1_slot
    model: str = ""
    base_url: str = ""
    dedicated: bool = False
    budget_tokens: int = 0
    budget_source: str = ""
    fallback_model: str = ""
    credential_source: str = "global"
    temperature: float | None = None


@dataclass(frozen=True)
class ToolStateSnapshot:
    """Реальные разрешения/доступность инструментов ДО планирования."""

    capabilities: tuple[str, ...] = ()      # что L1 может запросить сейчас
    announced: tuple[str, ...] = ()         # объявленные tools (allowlist)
    search_available: bool = False
    fetch_available: bool = False
    memory_available: bool = True
    source: str = "active_tools"


@dataclass(frozen=True)
class DeliveryPolicy:
    """Право/форма доставки: direct — force/direct-request, initiative — recheck."""

    kind: str = "text"                  # text | react | silent
    force_reply: bool = False           # прямое обращение: ответ обязателен
    direct_request: bool = False        # в чате ждёт прямого ответа человек
    recheck: bool = False               # инициатива: SendRecheck перед отправкой
    trigger: str = ""                   # серверный повод (funnel-метка)


@dataclass(frozen=True)
class TurnRequest:
    """§2.1: нормализованный объект ОДНОГО хода (данные, не поведение).

    Строится адаптерами входа (`DirectChatService.handle` — direct,
    `plan_initiative_decision`/`handle_initiative` — initiative) и целиком
    попадает в трассу хода (`direct_l1.record_turn_trace`), поэтому поля
    видны при инспекции, а не только «подразумеваются».

    Тексты чата здесь — недоверенные данные: в системные инструкции они не
    интерполируются.
    """

    trigger_type: str = TurnType.DIRECT.value
    chat_id: int = 0
    correlation_id: str = ""
    source_message_id: int | None = None
    raw_text: str = ""                       # ПОЛНЫЙ текст/caption, не preview
    media_markers: tuple[str, ...] = ()
    speaker_uid: int | None = None
    reply_parent: ReplyParentRef | None = None
    addressee: AddresseeRef | None = None
    aliases_snapshot: Mapping[int, str] = field(default_factory=dict)
    opportunity: OpportunityRef | None = None
    capabilities: tuple[str, ...] = ()
    tool_state: ToolStateSnapshot = field(default_factory=ToolStateSnapshot)
    model_slot: SlotBudgetMeta = field(default_factory=SlotBudgetMeta)
    delivery: DeliveryPolicy = field(default_factory=DeliveryPolicy)
    turn_started_at_utc: int = 0
    time_snapshot: "TimeSnapshot | None" = None

    @property
    def turn_type(self) -> str:
        """Тип хода (тот же резолв, что в `turn_policy`)."""
        return resolve_turn_type(self.trigger_type)


__all__ = [
    "TURN_POLICIES",
    "AddresseeRef",
    "DeliveryPolicy",
    "OpportunityRef",
    "ReplyParentRef",
    "SlotBudgetMeta",
    "ToolStateSnapshot",
    "TurnPolicy",
    "TurnRequest",
    "TurnType",
    "resolve_turn_type",
    "turn_policy",
]
