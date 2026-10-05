"""MCA-09 `mca-09-intents-initiative` — единый Intent-контур (ADR-1028-16 D1/D2/D5).

Один сервис/один store: `IntentStore` (durable v29 `mca_intents`), `IntentService`
(жизненный цикл/дедуп/архив/дисциплина/due-скан), `InitiativeCandidate` /
`InitiativeSituation` (структура кандидата: триггер → кандидат, НЕ автоотправка)
+ детерминированные помощники Decision (`decide_initiative`, silent/tool→silent,
случайность mca-10a read-only, ToolResult mca-11). Записи — только через
`write_transaction` (mca-01); события — единственный `emit_mca_event` (mca-13);
source refs — типизированные SourceRef/EvidenceLink (mca-04a); решение —
существующий `CoordinatorDecision` (direct_chat_service). Второй контур
отправки/второй движок решений/второй store НЕ создаются (GEN-R3).

Инварианты:
* R17: `goal`/`reason` — серверный канон ≤200 (без сырых цитат/секретов);
  в событиях/логах — только ID/коды/enum/числа/refs.
* Дисциплина обязательств: НЕ каждая фраза → обязательство; создание только по
  явному сигналу origin; намерение ≠ разрешение домогаться (`attempts` ≤
  `MCA_INTENT_MAX_ATTEMPTS` → `abandoned`, честное закрытие; игнор → deferred
  по событию `new_reply`/`topic_resume`, БЕЗ таймерного повтора).
* Жизненный цикл: `pending → deferred → fulfilled/abandoned/expired`;
  `deferred → pending` по событию; терминальное НЕ реактивируется — новый повод
  = новая АКТИВНАЯ запись (dedup-ключ освобождается, ссылка на предшественника
  через refs — spec §2 «merged_into_id/refs»; `merged_into_id` не занимается,
  чтобы запись была видима lifecycle/heartbeat-сканам).
* Тишина — нормальный исход: silent ничего не отправляет и не поднимает
  «желание» (решение чистое, без мутаций и таймеров).
* «500 сообщений на реплику» запрещено: модуль не читает окно сообщений.
* OFF (K1) = бит-в-бит 2.58.59: durable-входы инертны, джоб не регистрируется.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass

from services import mca_gates
from services.log_ring import sanitize

logger = logging.getLogger(__name__)

INTENT_POLICY_VERSION = "mca09-intent-1"

# ── закрытые наборы (spec §2/D2; ADR-1028-16 D2/D3/D5) ──────────────────────
INTENT_KINDS = frozenset({
    "follow_up", "answer_extension", "topic_interest", "open_dispute"})
INTENT_ORIGINS = frozenset({
    "unanswered_question", "explicit_request", "unfinished_topic",
    "search_result"})
INTENT_STATUSES = frozenset({
    "pending", "deferred", "fulfilled", "abandoned", "expired"})
INTENT_TERMINAL_STATUSES = frozenset({"fulfilled", "abandoned", "expired"})
ACTIVATION_CONDITIONS = frozenset({
    "time_due", "new_reply", "topic_resume", "event_change", "search_completed"})
TRIGGER_KINDS = frozenset({
    "new_message", "direct_address", "significant_event", "intent_due",
    "search_completed", "nostalgia_due"})
RECHECK_CONDITIONS = frozenset({
    "addressee_changed", "parent_changed", "intent_state_changed",
    "new_replies", "enabled_changed", "tool_permission_changed"})
CANDIDATE_SOURCES = frozenset({
    "intent", "memory", "nostalgia", "random", "search"})
# Структура семантики кандидата §14.10 — mca-09; применения 14.6–14.11 —
# mca-10b (второго action-schema нет).
COMMUNICATIVE_INTENTS = frozenset({
    "observation", "question", "opinion", "joke", "recall", "silence"})

# Инициативная доставка (kind для mca-22 ledger/UI-контракта; не wire).
DELIVERY_TEXT = "initiative_reply"
DELIVERY_REACT = "initiative_react"
DELIVERY_SILENT = "initiative_silent"
DELIVERY_TOOL = "initiative_tool"

# Серверный канон цели/причины (R17): без сырых цитат; кап 200 символов.
GOAL_MAX_CHARS = 200
REASON_MAX_CHARS = 200

_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:\-@]{1,120}$")
_WS_RE = re.compile(r"\s+")

# due-скан: overfetch для coalesce ≤1/чат, затем bounded-батч.
_DUE_OVERFETCH_FACTOR = 8


def _sha1_16(*parts) -> str:
    return hashlib.sha1("¦".join(str(p) for p in parts).encode("utf-8")
                        ).hexdigest()[:16]


def _now(ts=None) -> int:
    return int(time.time() if ts is None else ts)


def canon_text(value, cap: int = GOAL_MAX_CHARS) -> str | None:
    """Серверный канон (R17-safe): sanitize + схлопывание пробелов + кап.
    Секретоподобные значения маскируются sanitize'ом; пустое → None."""
    if value is None:
        return None
    try:
        text = _WS_RE.sub(" ", sanitize(str(value))).strip()
    except Exception:
        return None
    if not text:
        return None
    return text[:max(1, int(cap))]


def _tokens_json(values) -> str | None:
    """Устойчивые ID/refs (mca-03/mca-04a-стиль токенов) → JSON. R17:
    только печатаемые ID-токены, сырой текст запрещён."""
    out: list[str] = []
    for item in (values or ()):
        token = str(item or "").strip()
        if token and _SAFE_TOKEN_RE.match(token) and token not in out:
            out.append(token)
    return json.dumps(out, ensure_ascii=True) if out else None


def creation_allowed(origin, *, goal=None, source_refs=()) -> bool:
    """Дисциплина обязательств (T-5023, THR-2): origin допустим только при
    явном сигнале своего рода. НЕ каждая фраза → обязательство:
    * unanswered_question — каноническая цель (вопрос с будущей релевантностью);
    * explicit_request / unfinished_topic / search_result — ссылка на повод."""
    origin = str(origin or "")
    if origin not in INTENT_ORIGINS:
        return False
    has_goal = bool(canon_text(goal, GOAL_MAX_CHARS))
    has_refs = bool(list(source_refs or ()))
    if origin == "unanswered_question":
        return has_goal
    return has_refs and (has_goal or origin in ("explicit_request",
                                                "unfinished_topic"))


def _emit(event_name: str, *, outcome: str, chat_id=None,
          reason_code: str | None = None, level: str | None = None,
          **fields) -> None:
    """Notable-событие через единственный emit_mca_event (fail-open; R17)."""
    try:
        from services.mca_events import (LEVEL_INFO, LEVEL_WARN,
                                         emit_mca_event)
        if level is None:
            level = (LEVEL_WARN if outcome in ("failed", "silent", "abandoned")
                     else LEVEL_INFO)
        emit_mca_event(event_name, outcome=outcome, level=level,
                       component="intents", chat_id=chat_id,
                       reason_code=reason_code, **fields)
    except Exception:      # fail-open: событие не рвёт поток
        return


def _db_ready(db) -> bool:
    return (db is not None and hasattr(db, "db")
            and hasattr(db, "write_transaction"))


def _emit_close_event(status: str, *, reason_code: str, chat_id,
                      intent_id: str) -> None:
    """Notable-событие терминального перехода (литеральные call-site'ы —
    контракт сканера реестра mca-17a; R17-safe)."""
    if status == "fulfilled":
        _emit("intent_fulfilled", outcome="success", chat_id=chat_id,
              reason_code=reason_code, entity_id=intent_id)
    elif status == "abandoned":
        # честное закрытие без результата (не ошибка) — outcome `skipped`
        _emit("intent_abandoned", outcome="skipped", chat_id=chat_id,
              reason_code=reason_code, entity_id=intent_id)
    elif status == "expired":
        # срок истёк — честное закрытие без вопроса (код `intent_expired`)
        _emit("intent_abandoned", outcome="skipped", chat_id=chat_id,
              reason_code="intent_expired", entity_id=intent_id)


_INTENT_COLS = (
    "intent_id", "chat_id", "kind", "subject_ids_json", "topic_refs_json",
    "goal", "reason", "origin", "source_refs_json", "created_at", "updated_at",
    "not_before", "expires_at", "activation_condition", "status", "attempts",
    "last_evaluated_context_version", "priority", "linked_action_id",
    "dedup_key", "merged_into_id", "archived_at", "next_check_at")


def _row_dict(row) -> dict | None:
    if row is None:
        return None
    return {k: row[k] for k in _INTENT_COLS}


# ═════════════════════════════════════════════════════════════════════════════
# InitiativeCandidate / InitiativeSituation — триггер → кандидат, не отправка
# ═════════════════════════════════════════════════════════════════════════════

class InitiativeCandidate:
    """Кандидат инициативы (данные единого координатора; R17-safe).

    Никогда не отправляет сам: судьбу решает существующий CoordinatorDecision
    (аддитивный вход — единый контур, блок E)."""

    __slots__ = ("candidate_id", "trigger_kind", "chat_id", "intent_id",
                 "kind", "source", "goal", "priority", "reply_target",
                 "source_refs", "prepared_text_ref", "reason_code",
                 "admissible", "policy_version")

    def __init__(self, *, trigger_kind: str, chat_id: int, intent_id: str = "",
                 kind: str = "", source: str = "intent", goal: str = "",
                 priority: int = 0, reply_target: str | None = None,
                 source_refs: tuple = (), prepared_text_ref: str | None = None,
                 reason_code: str = "default",
                 admissible: bool = True,
                 policy_version: str = INTENT_POLICY_VERSION) -> None:
        self.trigger_kind = (trigger_kind if trigger_kind in TRIGGER_KINDS
                             else "")
        self.candidate_id = "trigger:%s:%s" % (
            self.trigger_kind or "unknown", _sha1_16(
                self.trigger_kind, int(chat_id), intent_id, goal))
        self.chat_id = int(chat_id)
        self.intent_id = str(intent_id or "")
        self.kind = str(kind if kind in INTENT_KINDS else "")
        self.source = (source if source in CANDIDATE_SOURCES else "intent")
        self.goal = str(goal or "")          # серверный канон ≤200
        self.priority = int(priority)
        self.reply_target = reply_target
        self.source_refs = tuple(source_refs or ())
        self.prepared_text_ref = prepared_text_ref
        self.reason_code = str(reason_code or "default")
        self.admissible = bool(admissible)
        self.policy_version = str(policy_version)

    def to_decision_candidate(self):
        """DecisionCandidate для `candidate_actions` (ленивый импорт —
        direct_chat_service сам импортирует этот модуль; цикла нет)."""
        from services.direct_chat_service import DecisionCandidate
        return DecisionCandidate(
            candidate_id=self.candidate_id, action="reply",
            reason_code=self.reason_code, source=self.source,
            source_refs=tuple(self.source_refs),
            prepared_text_ref=self.prepared_text_ref,
            intent_id=self.intent_id or None, priority=self.priority,
            admissible=self.admissible)


class InitiativeSituation:
    """Ситуация автономного решения (триггер + дешёвые сигналы уместности).

    Только ID/флаги/enum — R17-safe; заполняется дешёвыми гейтами триггера,
    БЕЗ чтения большого окна сообщений."""

    __slots__ = ("trigger_kind", "chat_id", "direct_pending",
                 "same_event_pending", "sensitive_moment", "relations_ok",
                 "bot_replied_recently", "reply_needed", "topic_open",
                 "open_intent_ids", "requested_source", "intent_id")

    def __init__(self, *, trigger_kind: str, chat_id: int,
                 direct_pending: bool = False, same_event_pending: bool = False,
                 sensitive_moment: bool = False, relations_ok: bool = True,
                 bot_replied_recently: bool = False, reply_needed: bool = False,
                 topic_open: bool = True, open_intent_ids=None,
                 requested_source: str | None = None,
                 intent_id: str | None = None) -> None:
        self.trigger_kind = (trigger_kind if trigger_kind in TRIGGER_KINDS
                             else "")
        self.chat_id = int(chat_id)
        # незавершённый direct-запрос: инициатива молчит (дедуп того же
        # события; direct приоритетен — квота фоновой инициативы не подавляет).
        self.direct_pending = bool(direct_pending)
        self.same_event_pending = bool(same_event_pending)
        self.sensitive_moment = bool(sensitive_moment)
        self.relations_ok = bool(relations_ok)
        self.bot_replied_recently = bool(bot_replied_recently)
        self.reply_needed = bool(reply_needed)
        self.topic_open = bool(topic_open)
        # None = набор неизвестен (фильтр не применяется); () = известен пустым.
        self.open_intent_ids = (None if open_intent_ids is None else
                                tuple(open_intent_ids))
        self.requested_source = requested_source
        self.intent_id = intent_id


def candidate_from_trigger(*, trigger_kind: str, chat_id: int,
                           intent_id: str = "", kind: str = "",
                           source: str = "intent", goal: str = "",
                           priority: int = 0, source_refs: tuple = (),
                           prepared_text_ref: str | None = None,
                           reason_code: str = "default",
                           ) -> InitiativeCandidate | None:
    """Триггер §13.1 → кандидат решения (НЕ автоотправка). Чистая функция:
    без БД, без LLM, без отправки; незнакомый триггер → None (тишина сама
    по себе кандидата не порождает)."""
    if not mca_gates.intents_enabled():
        return None
    if trigger_kind not in TRIGGER_KINDS:
        return None
    return InitiativeCandidate(
        trigger_kind=trigger_kind, chat_id=int(chat_id),
        intent_id=str(intent_id or ""), kind=str(kind or ""),
        source=str(source or "intent"), goal=str(goal or ""),
        priority=int(priority or 0), source_refs=tuple(source_refs or ()),
        prepared_text_ref=prepared_text_ref, reason_code=str(reason_code or ""))


# ── mca-10a: read-only копия метаданных (второй draw не делается) ────────────

def build_random_metadata(choice, requested_source: str | None = None) -> dict | None:
    """Копия метаданных существующего `ExplorationPolicy.choose` →
    `random_metadata` (незнакомые ключи отбрасываются).

    F-2: реальный mca-10a `PolicyChoice` несёт `source` (фактический источник
    draw), а не `actual_source`; `requested_source` берётся из аргумента/
    атрибута. Второй draw здесь НЕ делается."""
    if choice is None:
        return None
    meta: dict = {}
    actual = getattr(choice, "actual_source", None) \
        or getattr(choice, "source", None)
    requested = getattr(choice, "requested_source", None) \
        or requested_source or getattr(choice, "selected_source", None)
    for key, value in (("policy_version", getattr(choice, "policy_version",
                                                 None)),
                       ("fallback_reason", getattr(choice,
                                                   "fallback_reason", None)),
                       ("actual_source", actual),
                       ("requested_source", requested)):
        if value is None or not str(value).strip():
            continue
        meta[key] = str(value)[:120]
    draw_ids = [str(d)[:64] for d in (getattr(choice, "draw_ids", None) or ())
                if str(d or "").strip()]
    if draw_ids:
        meta["draw_ids"] = draw_ids
    probability = getattr(choice, "probability", None)
    if isinstance(probability, (int, float)) and \
            not isinstance(probability, bool):
        meta["probability"] = min(1.0, max(0.0, float(probability)))
    meta["deferred"] = bool(getattr(choice, "deferred", False))
    if requested_source and not meta.get("requested_source"):
        meta["requested_source"] = str(requested_source)[:120]
    return meta or None


def decide_initiative(*, situation: InitiativeSituation,
                      candidates=(), random_choice=None,
                      requested_source: str | None = None):
    """Единое инициативное решение (T-5029…T-5031) — детерминированный слой
    БЕЗ третьего LLM-вызова, БЕЗ SQL, БЕЗ draw: случайность приходит ГОТОВОЙ
    (`random_choice` — один `ExplorationPolicy.choose` на ситуацию, mca-10a).

    Уместность (spec §13.3): незавершённый direct/тот же event → молчание
    (direct приоритетен, дедуп только того же события); чувствительность/
    отношения → wrong_moment; недавняя своя реплика → recent_reply; пустой
    пул/закрытое намерение → no_eligible_alternative; отложенная случайность
    → random_fallback с bounded backoff (не nag-таймер — backoff только на
    необязательную инициативу, direct не затрагивается)."""
    from services.direct_chat_service import (ACTION_SILENT,
                                              CoordinatorDecision,
                                              REASON_DEFAULT,
                                              REASON_DISABLED,
                                              REASON_RECENT_REPLY)
    silent_codes: tuple = ()
    reason_code = REASON_DEFAULT
    next_check_at: int | None = None
    meta = build_random_metadata(random_choice,
                                 requested_source or situation.requested_source)
    pool = [c for c in (candidates or ()) if getattr(c, "admissible", True)]
    if not mca_gates.intent_decision_enabled():
        # K3/K1 OFF: инициативные решения не выполняются (честный disabled).
        reason_code = REASON_DISABLED
        silent_codes = ("disabled",)
    elif situation.direct_pending or situation.same_event_pending:
        # дедуп только того же события; квота/инициатива не подавляют direct.
        silent_codes = ("direct_update_dedup_hit",)
    elif situation.sensitive_moment or not situation.relations_ok or \
            not situation.topic_open:
        silent_codes = ("wrong_moment",)
    elif situation.bot_replied_recently and not situation.reply_needed:
        # Необходимость ответа (reply_needed) перевешивает «недавно отвечали»;
        # чувствительность/отношения остаются жёсткими стопами.
        reason_code = REASON_RECENT_REPLY
        silent_codes = ("wrong_moment",)
    elif getattr(random_choice, "deferred", False):
        # fallback-политика 10a: необязательная инициатива откладывается
        # (bounded backoff), direct жив.
        silent_codes = ("random_fallback",)
        next_check_at = _now() + max(60, int(
            mca_gates.intent_defer_backoff_seconds()))
    else:
        if situation.open_intent_ids is not None:
            open_set = set(situation.open_intent_ids)
            pool = [c for c in pool
                    if getattr(c, "intent_id", None) is None
                    or getattr(c, "intent_id") in open_set]
        pool = [c for c in pool
                if "no_new_contribution"
                not in tuple(getattr(c, "reason_codes", ()) or ())]
        if not pool:
            silent_codes = ("no_eligible_alternative",)
    selected = None
    if not silent_codes and pool:
        chosen = getattr(random_choice, "selected", None) \
            if random_choice is not None else None
        if (getattr(random_choice, "explored", False) and chosen is not None
                and any(c is chosen for c in pool) and
                getattr(chosen, "admissible", True)):
            selected = chosen          # exploration выиграл (один draw 10a)
        else:
            selected = max(pool, key=lambda c: int(
                getattr(c, "priority", 0) or 0))
        meta = build_random_metadata(random_choice, requested_source) or meta
    if silent_codes or selected is None:
        decision = CoordinatorDecision(
            intent="chat", addressee="unknown", memory_need=False,
            tool_calls=(), evaluation="none", action=ACTION_SILENT,
            trigger_kind=situation.trigger_kind, reason_code=reason_code,
            reason_codes=silent_codes, candidate_actions=tuple(candidates or ()),
            random_metadata=meta, next_check_at=next_check_at,
            intent_id=situation.intent_id)
        return decision
    action = getattr(selected, "action", "reply")
    decision = CoordinatorDecision(
        intent="chat",
        addressee="author" if situation.trigger_kind == "direct_address"
        else "unknown",
        memory_need=False, tool_calls=(), evaluation="none", action=action,
        trigger_kind=situation.trigger_kind,
        reason_code=getattr(selected, "reason_code", REASON_DEFAULT),
        reason_codes=tuple(getattr(selected, "reason_codes", ()) or ()),
        candidate_actions=tuple(candidates or ()),
        selected_candidate=getattr(selected, "candidate_id", None),
        random_metadata=meta,
        intent_id=getattr(selected, "intent_id", None) or situation.intent_id)
    return decision


def initiative_delivery_kind(decision) -> str:
    """Инициативный kind доставки (не wire-контракт; для ledger/наблюдения)."""
    action = getattr(decision, "action", "")
    if action == "silent":
        return DELIVERY_SILENT
    if action == "tool":
        return DELIVERY_TOOL
    if action == "react":
        return DELIVERY_REACT
    return DELIVERY_TEXT


def finish_tool_decision(decision, *, tool_outcome, forced: bool = False):
    """mca-11 (T-5033): завершить tool-ход типизированным статусом ToolResult
    (7 статусов). Инструмент не обязывает публиковать: неподходящий результат
    → silent + `tool_outcome` + reason_codes (tool→silent допустим ТОЛЬКО на
    нефорсированном/инициативном пути — A7 §43). `delivery_unknown` — без
    слепого повтора (никаких повторных заказов; молчание + defer за recheck-
    слоем). Учет расходов здесь НЕ ведётся (notable-only — механизм mca-11)."""
    from services.direct_chat_service import ACTION_SILENT, ACTION_TOOL
    from services.tool_result import (STATUS_OK, STATUS_EMPTY, STATUSES)
    status = str(tool_outcome) if tool_outcome is not None else None
    if status is None:
        return decision
    known = status in STATUSES
    decision.tool_outcome = status if known else None
    if status == STATUS_OK and known:
        return decision                       # итог публикуется (Stage-2)
    if forced:
        # explicit/вопрос/force — никогда silent (A7 §43): ход остаётся tool.
        return decision
    decision.action = ACTION_SILENT
    extras = list(decision.reason_codes or ())
    code = "no_new_contribution" if (known and status == STATUS_EMPTY) \
        else "insufficient_evidence"
    if code not in extras:
        extras.append(code)
    decision.reason_codes = tuple(extras)
    return decision


# ═════════════════════════════════════════════════════════════════════════════
# D4/T-5035: единый SendRecheck — проверка перед отправкой
# ═════════════════════════════════════════════════════════════════════════════

RECHECK_REASON_DISABLED = "disabled"
RECHECK_REASON_STALE = "stale_context"
RECHECK_REASON_CLOSED = "intent_closed"
RECHECK_REASON_ANSWERED = "already_answered"
RECHECK_REASON_DEFERRED = "recheck_deferred"
RECHECK_REASON_DENIED = "disabled"      # tool permission denied (тот же код)
CHUNK_LIMIT = 4096


@dataclass(frozen=True)
class RecheckContext:
    """R17-safe условия проверки перед отправкой (D4; порядок проверок —
    в `SendRecheck.check`). Активность в ПОСТОРОННЕЙ ветке в контексте не
    участвует — она готовый ответ НЕ отменяет (branch-scoped)."""

    enabled: bool = True
    addressee_ok: bool = True
    parent_changed: bool = False
    intent_row: dict | None = None
    already_answered: bool = False
    same_branch_replies: bool = False
    tool_permission_denied: bool = False
    context_version: str | None = None
    evaluated_context_version: str | None = None
    recheck_attempts: int = 0


@dataclass(frozen=True)
class RecheckOutcome:
    """Исход проверки: `proceed`; точная причина; ровно одна повторная
    оценка (`recheck_again`) → при повторной смене `defer` (`recheck_deferred`);
    `close_intent` — A15-закрытие (результат сообщён человеком)."""

    proceed: bool
    reason_code: str = ""
    recheck_again: bool = False
    defer: bool = False
    close_intent: str | None = None


class SendRecheck:
    """Единый слой проверок на границе отправки (spec §4/D4).

    Применяется для решений с непустыми `recheck_conditions` и для всех
    инициативных/отложенных отправок. K4 OFF (`MCA_SEND_RECHECK_ENABLED`) →
    новый слой не выполняется (документированное подмножество: существующие
    гейты остаются) — `proceed=True`."""

    def applies(self, decision) -> bool:
        """Нужна ли проверка: непустые recheck_conditions или инициативный
        trigger_kind. Обычный direct-ответ (пустые условия) не меняется."""
        return bool(getattr(decision, "recheck_conditions", ())) or \
            getattr(decision, "trigger_kind", "") in TRIGGER_KINDS

    def check(self, context: RecheckContext) -> RecheckOutcome:
        if not mca_gates.send_recheck_enabled():
            return RecheckOutcome(True, "")       # K4 OFF — подмножество
        if not context.enabled:
            return RecheckOutcome(False, RECHECK_REASON_DISABLED)
        if not context.addressee_ok or context.parent_changed:
            return RecheckOutcome(False, RECHECK_REASON_STALE)
        row = context.intent_row
        if row is not None and (
                str(row.get("status") or "") in INTENT_TERMINAL_STATUSES
                or row.get("merged_into_id")):
            # терминальное намерение не реактивируется: отправки нет.
            return RecheckOutcome(False, RECHECK_REASON_CLOSED)
        if context.already_answered or context.same_branch_replies:
            # A15: результат сообщён/ветка закрыта → закрыть без вопроса.
            return RecheckOutcome(False, RECHECK_REASON_ANSWERED,
                                  close_intent="fulfilled")
        if context.tool_permission_denied:
            # denied → без слепого повтора (повтор не заказывается).
            return RecheckOutcome(False, RECHECK_REASON_DENIED)
        if (context.context_version and context.evaluated_context_version
                and str(context.context_version)
                != str(context.evaluated_context_version)):
            if int(context.recheck_attempts or 0) <= 0:
                return RecheckOutcome(False, RECHECK_REASON_STALE,
                                      recheck_again=True)
            # повторная смена условий → отложить (бесконечного пересмотра нет)
            return RecheckOutcome(False, RECHECK_REASON_DEFERRED, defer=True)
        return RecheckOutcome(True, "")


def apply_recheck(decision, outcome: RecheckOutcome, *, now=None) -> bool:
    """Применить исход проверки к решению: `False` — отправка отменена
    (silent; при `defer` — серверное планирование, не nag-таймер)."""
    if outcome.proceed:
        return True
    from services.direct_chat_service import ACTION_SILENT
    decision.action = ACTION_SILENT
    if outcome.defer:
        decision.next_check_at = _now(now) + max(
            60, int(mca_gates.intent_defer_backoff_seconds()))
    if outcome.reason_code:
        codes = list(decision.reason_codes or ())
        if outcome.reason_code not in codes:
            codes.append(outcome.reason_code)
        decision.reason_codes = tuple(codes)
    return False


def chunk_text(text, *, limit: int = CHUNK_LIMIT) -> tuple[str, ...]:
    """Telegram-chunks ОДНОЙ логической отправки (T-5036).

    Проверка перед отправкой выполняется один раз ДО первого chunk — эта
    функция чистая и ничего не проверяет (разбиение не создаёт вторую
    логическую отправку)."""
    source = str(text or "")
    if not source:
        return ()
    limit = max(1, int(limit))
    if len(source) <= limit:
        return (source,)
    chunks: list[str] = []
    rest = source
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit + 1)
        if cut < limit // 2:
            cut = rest.rfind(" ", 0, limit + 1)
        if cut < limit // 2:
            cut = limit
        piece = rest[:cut].rstrip()
        chunks.append(piece or rest[:cut])
        rest = rest[cut:].lstrip("\n")
    if rest:
        chunks.append(rest)
    return tuple(chunks)


@dataclass(frozen=True)
class LogicalSendPlan:
    outcome: RecheckOutcome
    chunks: tuple[str, ...] = ()


def plan_logical_send(decision, *, recheck: SendRecheck,
                      context: RecheckContext, text,
                      limit: int = CHUNK_LIMIT) -> LogicalSendPlan:
    """Одна логическая отправка: recheck ровно один раз, затем chunks.

    Silent-решение не планирует отправку вовсе (silent ничего не отправляет) —
    `proceed=False` без chunks."""
    from services.direct_chat_service import ACTION_SILENT
    if getattr(decision, "action", "reply") == ACTION_SILENT:
        return LogicalSendPlan(outcome=RecheckOutcome(False, ""))
    outcome = (recheck.check(context) if recheck.applies(decision)
               else RecheckOutcome(True, ""))
    if not outcome.proceed:
        return LogicalSendPlan(outcome=outcome)
    return LogicalSendPlan(outcome=outcome,
                           chunks=chunk_text(text, limit=limit))


def chain_allowed(*, trigger_kind, intent_row: dict | None = None,
                  new_human_event: bool = False,
                  new_result: bool = False) -> bool:
    """T-5036: собственные сообщения не порождают следующее собственное
    сообщение без нового человеческого события/реального результата.

    `intent_due`: первая due-проверка допустима, после фактической попытки —
    только при новом событии/результате (intent после попытки — deferred на
    событие; таймерного повтора нет). Триггеры-события допустимы по
    определению (это и есть новое событие); `nostalgia_due` — свои гейты
    тишины/cooldown/анти-спама до подачи кандидата."""
    kind = str(trigger_kind or "")
    if kind in ("new_message", "direct_address", "significant_event",
                "search_completed", "nostalgia_due"):
        return True
    if kind == "intent_due":
        if new_human_event or new_result:
            return True
        return int((intent_row or {}).get("attempts") or 0) == 0
    return bool(new_human_event or new_result)


# ── наблюдаемость/границы (T-5039/T-5040) ────────────────────────────────────

#: локальный статус ситуации → контрактный outcome mca-13 (§17.1).
_INITIATIVE_OUTCOMES = {
    "ok": "success", "sent": "success", "silent": "silent",
    "cancelled": "cancelled", "candidate_ready": "skipped",
    "disabled": "skipped", "error": "failed",
}


def note_decision(decision, *, chat_id: int, outcome: str = "ok") -> None:
    """`initiative_decided` — ≤1 на ситуацию (notable-only; R17-safe:
    только ID/коды/enum/числа). Вызывается один раз финализатором ситуации.

    `outcome` — локальный статус ситуации; маппится в контрактный outcome
    mca-13 (иначе событие молча отбрасывается `build_event`)."""
    _emit("initiative_decided",
          outcome=_INITIATIVE_OUTCOMES.get(str(outcome or ""), "success"),
          chat_id=chat_id,
          reason_code=getattr(decision, "reason_code", None),
          entity_id=(getattr(decision, "intent_id", None) or None),
          stage=(getattr(decision, "trigger_kind", "") or None),
          status=(getattr(decision, "action", "") or None))


def apply_intent_bundle_signals(bundle, *, intent_row: dict | None = None,
                                recent_actions=(),
                                ambiguities=(), unknown=(),
                                contradictions=()):
    """T-5039/M-MCA07-2: заполнить поля ЕДИНОГО EvidenceBundle из оценки
    намерений (frozen bundle → `dataclasses.replace`; второй bundle не
    создаётся, retrieval не подменяется)."""
    actions = tuple(recent_actions or ())
    if intent_row and intent_row.get("linked_action_id"):
        linked = str(intent_row["linked_action_id"])
        if linked not in actions:
            actions = actions + (linked,)
    chosen = None
    if intent_row:
        chosen = str(intent_row.get("intent_id") or "") or None
    return dataclasses.replace(
        bundle, chosen_intent=chosen, recent_actions=actions,
        ambiguities=tuple(ambiguities or ()),
        unknown=tuple(unknown or ()),
        contradictions=tuple(contradictions or ()))


# ═════════════════════════════════════════════════════════════════════════════
# IntentStore — единственный durable-доступ к v29 `mca_intents`
# ═════════════════════════════════════════════════════════════════════════════

class IntentStore:
    """Записи — ТОЛЬКО `DatabaseService.write_transaction` (mca-01); чтения —
    bounded SQL по `mca_intents` (окно сообщений не читается никогда)."""

    def __init__(self, db):
        self._db = db

    async def get_intent(self, intent_id: str) -> dict | None:
        cursor = await self._db.db.execute(
            "SELECT * FROM mca_intents WHERE intent_id = ?",
            (str(intent_id),))
        return _row_dict(await cursor.fetchone())

    async def find_live_by_base(self, base_key: str) -> dict | None:
        cursor = await self._db.db.execute(
            "SELECT * FROM mca_intents WHERE dedup_key = ? "
            "AND status IN ('pending','deferred') AND merged_into_id IS NULL "
            "ORDER BY updated_at DESC LIMIT 1", (str(base_key),))
        return _row_dict(await cursor.fetchone())

    async def find_predecessor(self, base_key: str) -> dict | None:
        """Последняя завершённая строка канона (dedup-ключ освобождён
        суффиксом `#c:` при закрытии)."""
        cursor = await self._db.db.execute(
            "SELECT * FROM mca_intents WHERE dedup_key LIKE ? "
            "AND status IN ('fulfilled','abandoned','expired') "
            "ORDER BY updated_at DESC LIMIT 1", (str(base_key) + "#c:%",))
        return _row_dict(await cursor.fetchone())

    async def due_rows(self, now: int, limit: int) -> list[dict]:
        """Due-скан (pending/deferred, не слитые): наступил `next_check_at`
        либо `time_due`/`not_before`. Bounded LIMIT."""
        cursor = await self._db.db.execute(
            "SELECT * FROM mca_intents "
            "WHERE status IN ('pending','deferred') AND merged_into_id IS NULL "
            "AND ((next_check_at IS NOT NULL AND next_check_at <= ?) "
            "OR (activation_condition = 'time_due' AND not_before IS NOT NULL "
            "AND not_before <= ?)) "
            "ORDER BY priority DESC, "
            "COALESCE(next_check_at, not_before, created_at) ASC LIMIT ?",
            (int(now), int(now), max(1, int(limit))))
        return [_row_dict(r) for r in await cursor.fetchall()]

    async def expired_rows(self, now: int, limit: int) -> list[dict]:
        cursor = await self._db.db.execute(
            "SELECT intent_id FROM mca_intents "
            "WHERE status IN ('pending','deferred') AND merged_into_id IS NULL "
            "AND expires_at IS NOT NULL AND expires_at < ? LIMIT ?",
            (int(now), max(1, int(limit))))
        return [dict(r) for r in await cursor.fetchall()]

    async def archive_candidates(self, cutoff: int, limit: int) -> list[dict]:
        cursor = await self._db.db.execute(
            "SELECT intent_id, chat_id FROM mca_intents "
            "WHERE archived_at IS NULL AND updated_at < ? "
            "AND (status IN ('fulfilled','abandoned','expired') "
            "OR merged_into_id IS NOT NULL) ORDER BY updated_at ASC LIMIT ?",
            (int(cutoff), max(1, int(limit))))
        return [dict(r) for r in await cursor.fetchall()]

    async def prune_candidates(self, cutoff: int, limit: int) -> list[str]:
        """Retention-прун: АРХИВНЫЕ строки старше cutoff; активные не прунятся
        никогда (spec §8)."""
        cursor = await self._db.db.execute(
            "SELECT intent_id FROM mca_intents "
            "WHERE archived_at IS NOT NULL AND archived_at < ? "
            "ORDER BY archived_at ASC LIMIT ?",
            (int(cutoff), max(1, int(limit))))
        return [r["intent_id"] for r in await cursor.fetchall()]

    async def count_active(self, chat_id: int) -> int:
        cursor = await self._db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_intents WHERE chat_id = ? "
            "AND status IN ('pending','deferred') AND merged_into_id IS NULL",
            (int(chat_id),))
        row = await cursor.fetchone()
        return int(row["c"]) if row else 0

    async def list_active(self, chat_id: int,
                          limit: int = 100) -> list[dict]:
        cursor = await self._db.db.execute(
            "SELECT * FROM mca_intents WHERE chat_id = ? "
            "AND status IN ('pending','deferred') AND merged_into_id IS NULL "
            "ORDER BY priority DESC, updated_at DESC LIMIT ?",
            (int(chat_id), max(1, int(limit))))
        return [_row_dict(r) for r in await cursor.fetchall()]

    # ── writes (единый write-механизм mca-01) ────────────────────────────────
    async def insert(self, row: dict) -> None:
        async def _body(conn):
            await conn.execute(
                "INSERT INTO mca_intents (intent_id, chat_id, kind, "
                "subject_ids_json, topic_refs_json, goal, reason, origin, "
                "source_refs_json, created_at, updated_at, not_before, "
                "expires_at, activation_condition, status, attempts, "
                "last_evaluated_context_version, priority, linked_action_id, "
                "dedup_key, merged_into_id, archived_at, next_check_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row["intent_id"], int(row["chat_id"]), row["kind"],
                 row.get("subject_ids_json"), row.get("topic_refs_json"),
                 row.get("goal"), row.get("reason"), row["origin"],
                 row.get("source_refs_json"), int(row["created_at"]),
                 int(row["updated_at"]), row.get("not_before"),
                 row.get("expires_at"), row.get("activation_condition"),
                 row["status"], int(row.get("attempts") or 0),
                 row.get("last_evaluated_context_version"),
                 int(row.get("priority") or 0), row.get("linked_action_id"),
                 row["dedup_key"], row.get("merged_into_id"),
                 row.get("archived_at"), row.get("next_check_at")))

        await self._db.write_transaction(_body, op_name="mca09_intent_insert",
                                         chat_id=row.get("chat_id"))

    async def update_fields(self, intent_id: str, fields: dict) -> None:
        allowed = {k: v for k, v in (fields or {}).items()
                   if k in _INTENT_COLS and k not in ("intent_id",)}
        if not allowed:
            return
        sets = ", ".join(f"{k} = ?" for k in allowed)
        params = list(allowed.values()) + [str(intent_id)]

        async def _body(conn):
            await conn.execute(
                f"UPDATE mca_intents SET {sets} WHERE intent_id = ?", params)

        await self._db.write_transaction(_body, op_name="mca09_intent_update")

    async def release_dedup_key(self, intent_id: str) -> None:
        """Терминальное освобождает канонический dedup-ключ (суффикс `#c:`):
        новый повод = НОВАЯ запись, реактивации нет (UNIQUE сохраняется)."""

        async def _body(conn):
            await conn.execute(
                "UPDATE mca_intents SET dedup_key = dedup_key || '#c:' || "
                "intent_id WHERE intent_id = ? AND dedup_key NOT LIKE '%#c:%'",
                (str(intent_id),))

        await self._db.write_transaction(_body,
                                         op_name="mca09_intent_release_key")

    async def prune(self, intent_ids: list[str]) -> int:
        if not intent_ids:
            return 0

        async def _body(conn):
            total = 0
            for intent_id in intent_ids:
                cursor = await conn.execute(
                    "DELETE FROM mca_intents WHERE intent_id = ? "
                    "AND archived_at IS NOT NULL", (str(intent_id),))
                total += cursor.rowcount
            return total

        return int(await self._db.write_transaction(
            _body, op_name="mca09_intent_prune"))


# ═════════════════════════════════════════════════════════════════════════════
# IntentService — жизненный цикл / дедуп / дисциплина / due-скан
# ═════════════════════════════════════════════════════════════════════════════

def _ref_to_source_ref(chat_id: int, ref):
    """Типизированный ref (mca-04a): dict-спецификация или строка-токен →
    `provenance.SourceRef`. Невалидное → None (R17: только refs)."""
    from services import provenance as prov
    if isinstance(ref, dict):
        data = dict(ref)
        data.setdefault("chat_id", chat_id)
        try:
            return prov.SourceRef(
                store=str(data.get("store") or "sqlite"),
                entity_type=str(data.get("entity_type") or "unknown"),
                entity_id=str(data.get("entity_id") or ""),
                chat_id=(int(data["chat_id"])
                         if data.get("chat_id") is not None else None),
                revision=data.get("revision"),
                tg_message_id=data.get("tg_message_id"),
                dataset_id=data.get("dataset_id"),
                source_record_id=data.get("source_record_id"),
                resolution=str(data.get("resolution") or "resolved"),
            ).validate()
        except Exception:
            return None
    token = str(ref or "").strip()
    if not token or not _SAFE_TOKEN_RE.match(token):
        return None
    prefix, _, tail = token.partition(":")
    mapping = {
        "msg": ("sqlite", "message"), "message": ("sqlite", "message"),
        "user": ("telegram", "user"), "episode": ("sqlite", "episode"),
        "fact": ("sqlite", "graph_fact"), "lesson": ("sqlite", "lesson"),
        "search": ("external", "unknown"), "web": ("external", "unknown"),
        "topic": ("sqlite", "unknown"), "intent": ("sqlite", "intent"),
    }
    store, entity_type = mapping.get(prefix.lower(), ("sqlite", "unknown"))
    try:
        return prov.SourceRef(
            store=store, entity_type=entity_type, entity_id=token,
            chat_id=int(chat_id), resolution="resolved").validate()
    except Exception:
        return None


async def _register_source_refs(db, chat_id: int, intent_id: str,
                                refs) -> list[int]:
    """refs → mca_source_refs (get-or-create) + EvidenceLink «intent ← ref»
    (durable-связи — существующий механизм mca-04a; второго нет)."""
    from services import provenance as prov
    ids: list[int] = []
    try:
        intent_ref = await prov.resolve_source_ref(db, prov.SourceRef(
            store="sqlite", entity_type="intent", entity_id=str(intent_id),
            chat_id=int(chat_id), resolution="resolved"))
    except Exception:
        intent_ref = None
    for ref in (refs or ()):
        source_ref = _ref_to_source_ref(chat_id, ref)
        if source_ref is None:
            continue
        try:
            ref_id = await prov.resolve_source_ref(db, source_ref)
        except Exception:
            ref_id = None
        if ref_id is None:
            continue
        ids.append(int(ref_id))
        if intent_ref is not None:
            try:
                await prov.add_evidence_link(db, prov.EvidenceLink(
                    subject_ref_id=int(intent_ref), source_ref_id=int(ref_id),
                    link_type="derived_from", method="metadata",
                    verification="unknown", independence="unknown"))
            except Exception:
                pass
    return ids


class IntentService:
    """Единый сервис намерений (второго IntentService нет; OFF K1 → инертен)."""

    def __init__(self, db):
        self.db = db
        self.store = IntentStore(db)

    # ── создание (T-5020/T-5023) ─────────────────────────────────────────────
    def creation_allowed(self, origin, *, goal=None, source_refs=()) -> bool:
        return creation_allowed(origin, goal=goal, source_refs=source_refs)

    async def create_intent(self, chat_id: int, kind: str, origin: str, *,
                            subject_ids=(), topic_refs=(), goal=None,
                            reason=None, source_refs=(), not_before=None,
                            expires_at=None, activation_condition=None,
                            priority: int = 0, linked_action_id: str | None = None,
                            context_version: str | None = None,
                            created_at=None) -> tuple[str | None, bool]:
        """Создать намерение (или дедуп-слить с живым того же канона).

        Возвращает `(intent_id, created)`; дедуп-слияние → `(существующий,
        False)` + notable `intent_merged`. Дисциплина: без явного сигнала
        origin обязательство НЕ создаётся. Терминальный канон освобождает
        dedup-ключ → новый повод = НОВАЯ запись со ссылкой на предшественника
        (реактивации завершённого нет)."""
        if not mca_gates.intents_enabled():
            return None, False
        chat_id = int(chat_id)
        kind = str(kind or "")
        origin = str(origin or "")
        if kind not in INTENT_KINDS or origin not in INTENT_ORIGINS:
            return None, False
        if activation_condition is not None and \
                activation_condition not in ACTIVATION_CONDITIONS:
            return None, False
        if not creation_allowed(origin, goal=goal, source_refs=source_refs):
            return None, False
        if not _db_ready(self.db):
            return None, False
        ts = _now(created_at)
        canon_goal = canon_text(goal, GOAL_MAX_CHARS)
        canon_reason = canon_text(reason, REASON_MAX_CHARS)
        subject_json = _tokens_json(subject_ids)
        topic_json = _tokens_json(topic_refs)
        base_key = "intent:%s:%s:%s" % (
            chat_id, kind, _sha1_16(chat_id, kind, subject_json or "",
                                    topic_json or ""))
        try:
            live = await self.store.find_live_by_base(base_key)
            if live is not None:
                # Дедуп/слияние одинаковых (chat+kind+subject+topic).
                merged = {"updated_at": ts,
                          "goal": canon_goal or live.get("goal"),
                          "reason": canon_reason or live.get("reason"),
                          "priority": max(int(live.get("priority") or 0),
                                          int(priority or 0))}
                if not_before is not None:
                    merged["not_before"] = int(not_before)
                    if live.get("status") == "pending":
                        merged["next_check_at"] = int(not_before)
                if expires_at is not None:
                    merged["expires_at"] = int(expires_at)
                if live.get("status") == "deferred":
                    # deferred → pending по новому событию (не таймер).
                    merged["status"] = "pending"
                    merged["next_check_at"] = None
                await self.store.update_fields(live["intent_id"], merged)
                _emit("intent_merged", outcome="success", chat_id=chat_id,
                      reason_code="intent_merged",
                      entity_id=live["intent_id"])
                return live["intent_id"], False
            predecessor = await self.store.find_predecessor(base_key)
            intent_id = "intent:%s:%s:%s" % (
                chat_id, kind, _sha1_16(base_key, ts))
            # F-1: ссылка на предшественника — через refs (spec §2:
            # «merged_into_id/refs»), НЕ через merged_into_id: active-сканы
            # (`due_rows`/`count_active`/`find_live_by_base`) исключают строки
            # с `merged_into_id IS NOT NULL`, поэтому активная новая запись с
            # такой ссылкой была бы невидима для lifecycle/heartbeat.
            refs_all = list(source_refs or ())
            if predecessor is not None:
                refs_all.append(f"intent:{predecessor['intent_id']}")
            refs_ids = await _register_source_refs(
                self.db, chat_id, intent_id, refs_all)
            row = {
                "intent_id": intent_id, "chat_id": chat_id, "kind": kind,
                "subject_ids_json": subject_json, "topic_refs_json": topic_json,
                "goal": canon_goal, "reason": canon_reason, "origin": origin,
                "source_refs_json": (json.dumps(refs_ids) if refs_ids
                                     else None),
                "created_at": ts, "updated_at": ts,
                "not_before": (int(not_before) if not_before is not None
                               else None),
                "expires_at": (int(expires_at) if expires_at is not None
                               else None),
                "activation_condition": activation_condition,
                "status": "pending", "attempts": 0,
                "last_evaluated_context_version": (
                    str(context_version)[:120] if context_version else None),
                "priority": int(priority or 0),
                "linked_action_id": linked_action_id,
                # F-1: предшественник — в refs (см. выше), не в
                # merged_into_id (иначе активная запись невидима сканам).
                "merged_into_id": None,
                "archived_at": None,
                # серверное планирование due-проверки: от `not_before`.
                "next_check_at": (int(not_before) if not_before is not None
                                  else None),
            }
            row["dedup_key"] = base_key
            await self.store.insert(row)
            _emit("intent_created", outcome="success", chat_id=chat_id,
                  reason_code="intent_created", entity_id=intent_id)
            return intent_id, True
        except Exception:
            logger.warning("[mca09] intent create failed | chat=%s kind=%s",
                           chat_id, kind, exc_info=True)
            return None, False

    # ── переходы (T-5021; терминальное не флипается) ─────────────────────────
    async def _transition(self, intent_id: str, *, to_status: str,
                          reason_code: str, extra: dict | None = None,
                          event: str | None = None, now=None) -> dict | None:
        row = await self.store.get_intent(intent_id)
        if row is None or row["status"] not in ("pending", "deferred"):
            return None
        fields = {"status": to_status, "updated_at": _now(now)}
        fields.update(extra or {})
        if to_status in INTENT_TERMINAL_STATUSES:
            fields["next_check_at"] = None
        await self.store.update_fields(intent_id, fields)
        if to_status in INTENT_TERMINAL_STATUSES:
            await self.store.release_dedup_key(intent_id)
            _emit_close_event(to_status, reason_code=reason_code,
                              chat_id=row["chat_id"], intent_id=intent_id)
        elif event:
            _emit(event, outcome="skipped", chat_id=row["chat_id"],
                  reason_code=reason_code, entity_id=intent_id)
        return {**row, **fields}

    async def defer(self, intent_id: str, *, next_check_at: int | None = None,
                    activation_condition: str | None = None, reason_code:
                    str = "wrong_moment", now=None) -> dict | None:
        """pending → deferred (event-based ожидание; БЕЗ таймерного повтора)."""
        if not mca_gates.intents_enabled():
            return None
        if activation_condition is not None and \
                activation_condition not in ACTIVATION_CONDITIONS:
            return None
        return await self._transition(
            intent_id, to_status="deferred", reason_code=reason_code,
            extra={"next_check_at": (int(next_check_at) if next_check_at
                                     is not None else None),
                   "activation_condition": activation_condition},
            event="recheck_deferred", now=now)

    async def resume_on_event(self, intent_id: str, *, event_kind: str,
                              now=None) -> dict | None:
        """deferred → pending по событию (`new_reply`/`topic_resume`/…);
        pending — no-op (None); терминальное НЕ активируется (None)."""
        if not mca_gates.intents_enabled():
            return None
        if event_kind not in TRIGGER_KINDS:
            return None
        row = await self.store.get_intent(intent_id)
        if row is None or row["status"] != "deferred":
            return None
        ts = _now(now)
        fields = {"status": "pending", "next_check_at": ts, "updated_at": ts}
        await self.store.update_fields(intent_id, fields)
        return {**row, **fields}

    async def mark_attempt(self, intent_id: str, *, now=None) -> dict | None:
        """Фактическая попытка (не «домогательство»): мы спросили — результата
        нет → deferred на событие (`new_reply`, БЕЗ таймера); после
        `MCA_INTENT_MAX_ATTEMPTS` → `abandoned` (честное закрытие)."""
        if not mca_gates.intents_enabled():
            return None
        row = await self.store.get_intent(intent_id)
        if row is None or row["status"] not in ("pending", "deferred"):
            return None
        attempts = int(row.get("attempts") or 0) + 1
        cap = max(1, int(mca_gates.intent_max_attempts()))
        if attempts >= cap:
            return await self._transition(
                intent_id, to_status="abandoned",
                reason_code="intent_expired", extra={"attempts": attempts},
                event="intent_abandoned", now=now)
        ts = _now(now)
        fields = {"attempts": attempts, "status": "deferred",
                  "activation_condition": "new_reply", "next_check_at": None,
                  "updated_at": ts}
        await self.store.update_fields(intent_id, fields)
        _emit("recheck_deferred", outcome="skipped",
              chat_id=row["chat_id"], reason_code="wrong_moment",
              entity_id=intent_id)
        return {**row, **fields}

    async def close(self, intent_id: str, *, status: str,
                    reason_code: str = "already_answered",
                    now=None) -> dict | None:
        """Закрытие результатом/отказом (A15: результат сообщён → закрыто
        БЕЗ повторного вопроса). Терминальное не перезакрывается."""
        if not mca_gates.intents_enabled():
            return None
        status = str(status or "")
        if status not in ("fulfilled", "abandoned"):
            return None
        return await self._transition(
            intent_id, to_status=status, reason_code=str(reason_code or ""),
            event=("intent_fulfilled" if status == "fulfilled"
                   else "intent_abandoned"), now=now)

    # ── триггеры/due-скан/heartbeat (T-5025/T-5026) ───────────────────────────
    async def due_candidates(self, *, now=None) -> list[InitiativeCandidate]:
        """Due-скан SQL: bounded-батч (≤ `MCA_INTENT_HEARTBEAT_BATCH_MAX`,
        coalesce ≤1 кандидат/чат/тик); deferred с наступившим сроком →
        pending. Без LLM; только SQL по `mca_intents`."""
        if not mca_gates.intent_heartbeat_enabled():
            return []
        ts = _now(now)
        batch = max(1, int(mca_gates.intent_heartbeat_batch_max()))
        rows = await self.store.due_rows(ts, batch * _DUE_OVERFETCH_FACTOR)
        candidates: list[InitiativeCandidate] = []
        seen_chats: set[int] = set()
        for row in rows:
            chat_id = int(row["chat_id"])
            if chat_id in seen_chats:
                continue                     # coalesce ≤1 кандидат/чат/тик
            if row["status"] == "deferred":
                await self.resume_on_event(row["intent_id"],
                                           event_kind="significant_event",
                                           now=ts)
            seen_chats.add(chat_id)
            candidates.append(InitiativeCandidate(
                trigger_kind="intent_due", chat_id=chat_id,
                intent_id=row["intent_id"], kind=row["kind"],
                goal=row.get("goal") or "",
                priority=int(row.get("priority") or 0)))
            if len(candidates) >= batch:
                break
        return candidates

    async def hygiene(self, *, now=None) -> dict:
        """Гигиена накопления (T-5022): просроченные → `expired`; завершённые
        старше `MCA_INTENT_RETENTION_DAYS` → `archived_at` (+ retention-прун
        архивных). Активные не прунятся; монотонного роста нет."""
        stats = {"expired": 0, "abandoned": 0, "archived": 0, "pruned": 0}
        if not mca_gates.intents_enabled():
            return stats
        ts = _now(now)
        days = max(1, int(mca_gates.intent_retention_days()))
        for row in await self.store.expired_rows(ts, limit=100):
            result = await self._transition(
                row["intent_id"], to_status="expired",
                reason_code="intent_expired", now=ts)
            if result is not None:
                stats["expired"] += 1
        cutoff = ts - days * 86400
        for row in await self.store.archive_candidates(cutoff, limit=200):
            await self.store.update_fields(row["intent_id"],
                                           {"archived_at": ts})
            _emit("intent_archived", outcome="success",
                  chat_id=row["chat_id"], reason_code="intent_archived",
                  entity_id=row["intent_id"])
            stats["archived"] += 1
        stats["pruned"] = await self.store.prune(
            await self.store.prune_candidates(cutoff, limit=500))
        if any(stats.values()):
            logger.info("[mca09] hygiene | expired=%d archived=%d pruned=%d",
                        stats["expired"], stats["archived"], stats["pruned"])
        return stats

    async def heartbeat_tick(self, *, now=None) -> dict:
        """Лёгкий тик (T-5026): due-намерения без LLM-вызова и без чтения
        окна; + гигиена. OFF (K1/K2) → инертен (0 SQL)."""
        if not mca_gates.intents_enabled() or \
                not mca_gates.intent_heartbeat_enabled():
            return {"enabled": False, "due": [], "expired": 0, "abandoned": 0,
                    "archived": 0}
        if not _db_ready(self.db):
            return {"enabled": False, "due": [], "expired": 0, "abandoned": 0,
                    "archived": 0}
        clean = await self.hygiene(now=now)
        due = await self.due_candidates(now=now)
        return {"enabled": True, "due": due, "expired": clean["expired"],
                "abandoned": clean["abandoned"], "archived": clean["archived"]}

    async def list_active(self, chat_id: int) -> list[dict]:
        if not mca_gates.intents_enabled():
            return []
        return await self.store.list_active(chat_id)


def get_service(db) -> IntentService:
    """Фасад (единственный контур; второго сервиса/store нет)."""
    return IntentService(db)


async def heartbeat_tick(db, *, now=None) -> dict:
    """Тик хоста `intent_heartbeat_tick` (MemoryMaintenanceService, 300 с):
    due-скан + гигиена БЕЗ LLM и без чтения окна. Кандидаты отдаются единому
    координатор-контуру; тик сам НИЧЕГО не отправляет (fail-open)."""
    stats = {"status": "disabled", "due": 0, "candidates": 0, "chats": 0}
    try:
        if not mca_gates.intents_enabled() or \
                not mca_gates.intent_heartbeat_enabled() or \
                not _db_ready(db):
            return stats
        result = await get_service(db).heartbeat_tick(now=now)
        due = result.get("due") or []
        stats.update(status="ok" if result.get("enabled") else "disabled",
                     due=len(due), candidates=len(due),
                     chats=len({c.chat_id for c in due}))
        return stats
    except Exception:
        logger.warning("[mca09] heartbeat tick failed", exc_info=True)
        stats["status"] = "error"
        return stats
