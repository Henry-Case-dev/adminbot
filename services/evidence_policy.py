"""ASAP-EVIDENCE-ROUTING-01 v3 §1: runtime evidence policy (чистые функции).

Единственная семантика модуля — «нужна ли этому ходу внешняя read-only
проверка и какая именно». Класс берётся из **планируемого содержания**
ответа (поля уже существующего L1-плана + optional ``external_claims`` в том
же единственном L1-вызове), а не из темы входящего текста.

Границы (замороженный контракт
``plans/features/evol/arch/evidence-routing-contract.md`` §1.1):

* без LLM, без БД, без сети, без I/O — вход/выход полностью детерминирован;
* никакого второго классификатора и второго Writer'а;
* новые словари фраз не заводятся: явные поручения берутся из существующих
  детекторов (``direct_capabilities.detect_action_intent``,
  ``temporal_factcheck.is_referential_claim``, ``smartmodule_urls.extract_urls``)
  и передаются сюда вызывающим как :class:`ExplicitRequest`;
* разрешение инструментов — ОДНА точка :func:`allowed` с фиксированным
  порядком проверок (§1.5). Асинхронное состояние (RBAC, реальная
  доступность провайдера/ключа/квоты через ``capability_registry.resolve``)
  собирает вызывающий в :class:`EvidenceContext`; модуль остаётся чистым.

Словарь ``reason_code`` не дублируется: enum'ы живут здесь и конвертируются
в существующий ``mca_events.REASON_CODES`` ровно один раз, на границе
события (:func:`skip_reason_code` / :func:`failure_reason_code`).
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field, replace
from enum import Enum

__all__ = [
    "ClaimKey", "EvidenceDecision", "ExplicitRequest", "SuppliedSources",
    "RuntimeState", "EvidenceContext", "EvidenceSkipReason",
    "EvidenceFailureCode", "EvidenceClass", "EVIDENCE_CLASSES",
    "CLAIM_RELATIONS", "FACTUAL_ACTS", "SOCIAL_ACTS", "FACTUAL_STRUCTURES",
    "evaluate_evidence_need", "allowed", "effective_capabilities",
    "mark_required_unmet",
    "classify_claims", "claims_coverage", "delivered_claim_keys",
    "skip_reason_code",
    "failure_reason_code", "blocked_reason_code", "policy_enabled",
    "egress_guard_enabled", "guard_egress", "drop_claim_sentence",
    "EgressVerdict", "GUARD_NONE", "GUARD_HINT_RETRY",
    "GUARD_ONE_LOOKUP", "GUARD_DROP_CLAIM", "GUARD_SKIP_CLASSES",
    "runtime_source_note",
    "is_runtime_self_question", "is_external_forbidden",
    "is_attributed_speech", "claims_query",
    "REASON_EVIDENCE_SKIPPED",
    "REASON_EVIDENCE_REUSED", "REASON_EVIDENCE_CLAIM_REMOVED",
    "EVIDENCE_STAGE", "CAPABILITY_SOURCE_READ",
]

# ── закрытые перечисления §1.1 / §1.4 ───────────────────────────────────────

#: Классы содержания ответа (§1.1). ``str``-наследник — R17-safe значения
#: уходят в события/JSON без сериализации enum'ов.
EvidenceClass = str

EVIDENCE_CLASSES = ("externally_factual", "attributed", "background",
                    "social", "transformation", "runtime", "historical")

#: Закрытый набор relation claim-key (§1.1/§3.2).
CLAIM_RELATIONS = ("exists", "version", "spec", "price", "date", "event",
                   "comparison")

#: Акты плана, которые сами по себе несут внешний факт (§1.2 п.6).
FACTUAL_ACTS = frozenset({"answer", "explanation", "disagreement", "research",
                          "comparison"})

#: Структуры ответа, которые сами по себе несут внешний факт (§1.2 п.6).
FACTUAL_STRUCTURES = frozenset({"answer", "explanation", "report",
                                "comparison"})

#: Социально-творческие акты без внешнего claim (§1.2 п.7).
SOCIAL_ACTS = frozenset({"agreement", "banter", "tease", "emotional_reply",
                         "support", "creative", "hostile_rebuff"})


class EvidenceSkipReason(str, Enum):
    """Нормальное основание НЕ делать внешний вызов (§1.4, 12 значений)."""

    SILENT_OR_REACT_ONLY = "silent_or_react_only"
    NO_NEW_EXTERNAL_CLAIM = "no_new_external_claim"
    PURE_SOCIAL_OR_CREATIVE = "pure_social_or_creative"
    ATTRIBUTED_HISTORY_OR_SUMMARY = "attributed_history_or_summary"
    TEXT_TRANSFORM_OR_TRANSLATION = "text_transform_or_translation"
    SUFFICIENT_RUNTIME_SOURCE = "sufficient_runtime_source"
    SUFFICIENT_CHAT_HISTORY_SOURCE = "sufficient_chat_history_source"
    SUFFICIENT_SUPPLIED_SOURCE = "sufficient_supplied_source"
    SOURCE_READER_ALREADY_FETCHED = "source_reader_already_fetched"
    QUALIFIED_VERIFIED_REUSE = "qualified_verified_reuse"
    USER_FORBIDS_EXTERNAL = "user_forbids_external"
    RBAC_OR_PRIVACY_BLOCKED = "rbac_or_privacy_blocked"


class EvidenceFailureCode(str, Enum):
    """Обязательная, но НЕ выполненная проверка — не исключение (§1.4)."""

    SEARCH_PROVIDER_DOWN = "search_provider_down"
    SOURCE_FETCH_FAILED = "source_fetch_failed"
    BUDGET_OR_DEADLINE = "budget_or_deadline"
    QUOTA_EXHAUSTED = "quota_exhausted"
    NETWORK_UNAVAILABLE = "network_unavailable"
    MEDIUM_NOT_READY = "medium_not_ready"
    NO_RELEVANT_RESULTS = "no_relevant_results"
    CAPABILITY_NOT_READY = "capability_not_ready"


#: Подпричина skip'а → существующий ``mca_events.REASON_CODES`` (§1.4).
#: `SUFFICIENT_CHAT_HISTORY_SOURCE` различает «найдено»/«не найдено».
_SKIP_TO_REASON = {
    EvidenceSkipReason.SILENT_OR_REACT_ONLY: "stage_skipped",
    EvidenceSkipReason.NO_NEW_EXTERNAL_CLAIM: "stage_skipped",
    EvidenceSkipReason.PURE_SOCIAL_OR_CREATIVE: "stage_skipped",
    EvidenceSkipReason.ATTRIBUTED_HISTORY_OR_SUMMARY: "already_answered",
    EvidenceSkipReason.TEXT_TRANSFORM_OR_TRANSLATION: "stage_skipped",
    EvidenceSkipReason.SUFFICIENT_RUNTIME_SOURCE: "already_answered",
    EvidenceSkipReason.SUFFICIENT_CHAT_HISTORY_SOURCE: "already_answered",
    EvidenceSkipReason.SUFFICIENT_SUPPLIED_SOURCE: "stage_skipped",
    EvidenceSkipReason.SOURCE_READER_ALREADY_FETCHED: "provenance_linked",
    EvidenceSkipReason.QUALIFIED_VERIFIED_REUSE: "exact_match_used",
    # Контракт §1.4 называет для этого случая «новый external_tools_disabled»,
    # но там же санкционирует РОВНО три новых кода (остальные — существующие).
    # 3-кодовая санкция приоритетна; `disabled` уже означает «модуль/канал
    # выключен» и остаётся честной причиной пропуска внешнего вызова.
    EvidenceSkipReason.USER_FORBIDS_EXTERNAL: "disabled",
    EvidenceSkipReason.RBAC_OR_PRIVACY_BLOCKED: "job_not_allowed",
}

#: Failure code → существующий ``mca_events.REASON_CODES`` (§1.4).
_FAILURE_TO_REASON = {
    EvidenceFailureCode.SEARCH_PROVIDER_DOWN: "provider_unavailable",
    EvidenceFailureCode.SOURCE_FETCH_FAILED: "source_missing",
    EvidenceFailureCode.BUDGET_OR_DEADLINE: "deadline_exceeded",
    EvidenceFailureCode.QUOTA_EXHAUSTED: "financial_limit_reached",
    EvidenceFailureCode.NETWORK_UNAVAILABLE: "provider_unavailable",
    EvidenceFailureCode.MEDIUM_NOT_READY: "stage_waiting_external",
    EvidenceFailureCode.NO_RELEVANT_RESULTS: "retrieval_empty",
    # Существующий код Л1-слоя (`direct_capabilities.REASON_NOT_READY`), а не
    # новое значение словаря mca_events.
    EvidenceFailureCode.CAPABILITY_NOT_READY: "capability_not_ready",
}

#: Коды, которые ``allowed()`` возвращает при отказе (§1.5).
BLOCK_RBAC = "job_not_allowed"
BLOCK_EXTERNAL_DISABLED = "disabled"
BLOCK_PROVIDER_UNCONFIGURED = "provider_unconfigured"
BLOCK_PROVIDER_UNAVAILABLE = "provider_unavailable"
BLOCK_TOOL_ABSENT = "tool_absent"
BLOCK_CAPABILITY_NOT_READY = "capability_not_ready"
BLOCK_QUOTA = "financial_limit_reached"
BLOCK_SSRF = "destination_blocked"
BLOCK_PRIVACY = "privacy_blocked"

_BLOCK_TO_FAILURE = {
    BLOCK_RBAC: EvidenceFailureCode.CAPABILITY_NOT_READY,
    BLOCK_EXTERNAL_DISABLED: EvidenceFailureCode.NETWORK_UNAVAILABLE,
    BLOCK_PROVIDER_UNCONFIGURED: EvidenceFailureCode.SEARCH_PROVIDER_DOWN,
    BLOCK_PROVIDER_UNAVAILABLE: EvidenceFailureCode.SEARCH_PROVIDER_DOWN,
    BLOCK_TOOL_ABSENT: EvidenceFailureCode.CAPABILITY_NOT_READY,
    BLOCK_CAPABILITY_NOT_READY: EvidenceFailureCode.CAPABILITY_NOT_READY,
    BLOCK_QUOTA: EvidenceFailureCode.QUOTA_EXHAUSTED,
    BLOCK_SSRF: EvidenceFailureCode.SOURCE_FETCH_FAILED,
    BLOCK_PRIVACY: EvidenceFailureCode.CAPABILITY_NOT_READY,
}

#: Три НОВЫХ кода ``mca_events.REASON_CODES`` (ровно столько, §1.4).
REASON_EVIDENCE_SKIPPED = "evidence_skipped"
REASON_EVIDENCE_REUSED = "evidence_reused"
REASON_EVIDENCE_CLAIM_REMOVED = "evidence_unverified_claim_removed"

#: Имя стадии для событий политики (R17-safe).
EVIDENCE_STAGE = "evidence_policy"

#: Capability чтения исходников (EVOL-SRC-READER, `PENDING`): до реализации
#: `allowed()` честно отвечает `capability_not_ready`, а не «пропускаем».
CAPABILITY_SOURCE_READ = "source_read"
_SOURCE_READER_READY = False


def skip_reason_code(reason, *, found: bool = True) -> str:
    """Подпричина skip'а → ``mca_events``-код (ровно одна конвертация)."""
    try:
        key = (reason if isinstance(reason, EvidenceSkipReason)
               else EvidenceSkipReason(str(reason)))
    except ValueError:
        return "stage_skipped"
    if key is EvidenceSkipReason.SUFFICIENT_CHAT_HISTORY_SOURCE and not found:
        return "no_relevant_memory"
    return _SKIP_TO_REASON.get(key, "stage_skipped")


def failure_reason_code(code) -> str:
    """Failure code → ``mca_events``-код."""
    try:
        key = (code if isinstance(code, EvidenceFailureCode)
               else EvidenceFailureCode(str(code)))
    except ValueError:
        return "insufficient_evidence"
    return _FAILURE_TO_REASON.get(key, "insufficient_evidence")


def blocked_reason_code(block_code: str, *, user_forbids: bool = False) -> str:
    """Код отказа ``allowed()`` → ``mca_events``-код (не молчаливый).

    Выключенный рубильник сети/явный запрет пользователя — существующий код
    ``disabled`` (новых кодов сверх трёх санкционированных не заводим)."""
    code = str(block_code or "")
    return {
        BLOCK_EXTERNAL_DISABLED: "disabled",
        BLOCK_RBAC: "job_not_allowed",
        BLOCK_PROVIDER_UNCONFIGURED: "provider_unconfigured",
        BLOCK_PROVIDER_UNAVAILABLE: "provider_unavailable",
        BLOCK_TOOL_ABSENT: "tool_absent",
        BLOCK_CAPABILITY_NOT_READY: "capability_not_ready",
        BLOCK_QUOTA: "financial_limit_reached",
        BLOCK_SSRF: "destination_blocked",
        BLOCK_PRIVACY: "job_not_allowed",
    }.get(code, "insufficient_evidence")


# ── claim-key (§3.2) ────────────────────────────────────────────────────────


def _canon(value) -> str:
    """Канон одного поля claim-key (существующий `claim_envelope`-канон)."""
    try:
        from services.claim_envelope import normalize_proposition
        norm = normalize_proposition(str(value or ""))
    except Exception:      # pragma: no cover - защитная ветка
        norm = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    return norm or ""


@dataclass(frozen=True)
class ClaimKey:
    """Канонический ключ claim: сущность+предмет+версия+дата+метрика.

    «Тема та же» доказательством НЕ является: другая версия/дата/метрика —
    другой ключ, а значит и reuse не засчитывается (§3.2/§3.3)."""

    entity: str
    relation: str
    version: str = ""
    date: str = ""
    metric: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity", _canon(self.entity))
        relation = str(self.relation or "").strip().lower()
        object.__setattr__(self, "relation",
                           relation if relation in CLAIM_RELATIONS else "exists")
        object.__setattr__(self, "version", _canon(self.version))
        object.__setattr__(self, "date", _canon(self.date))
        object.__setattr__(self, "metric", _canon(self.metric))

    @property
    def complete(self) -> bool:
        return bool(self.entity)

    def key(self) -> str:
        """``sha1(entity|relation|version|date|metric)[:16]``."""
        raw = "|".join((self.entity, self.relation, self.version, self.date,
                        self.metric))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def classify_claims(plan) -> tuple[ClaimKey, ...]:
    """Allowlisted ``plan.external_claims`` → валидные :class:`ClaimKey`.

    Невалидный элемент отбрасывается (план не инвалидируется); отсутствие
    поля/пустой список → ``()``. Никогда не бросает."""
    try:
        raw = getattr(plan, "external_claims", ()) or ()
    except Exception:      # pragma: no cover - защитная ветка
        return ()
    out: list[ClaimKey] = []
    seen: set[str] = set()
    for item in raw:
        key: ClaimKey | None = None
        if isinstance(item, ClaimKey):
            key = item if item.complete else None
        elif isinstance(item, str):
            key = ClaimKey(entity=item) if _canon(item) else None
        elif isinstance(item, dict):
            entity = _canon(item.get("entity"))
            if entity:
                key = ClaimKey(
                    entity=entity,
                    relation=str(item.get("relation") or "exists"),
                    version=str(item.get("version") or ""),
                    date=str(item.get("date") or ""),
                    metric=str(item.get("metric") or ""))
        if key is None or not key.complete:
            continue
        digest = key.key()
        if digest in seen:
            continue
        seen.add(digest)
        out.append(key)
    return tuple(out)


# ── входы политики (§1.1/§1.3) ──────────────────────────────────────────────


@dataclass(frozen=True)
class ExplicitRequest:
    """Детерминированно распознанное поручение (§1.3).

    Значения заполняет вызывающий ИЗ СУЩЕСТВУЮЩИХ детекторов:
    ``search`` — ``direct_capabilities.detect_action_intent``
    (``INTENT_WEB_SEARCH``) / ``direct_execution._SEARCH_RE``; ``verify`` —
    явная ФОРМА просьбы проверить факт (``direct_capabilities.
    is_explicit_factcheck_request`` поверх маркеров ``INTENT_FACT_CHECK``) и
    ``temporal_factcheck.is_referential_claim`` («проверь это» на reply);
    ``recheck`` — optional-поле плана L1 (решение Architect «г»): человек
    просит проверить заново/освежить, формулировку которых нет ни в одном
    детерминированном детекторе; ``read_source`` — поручение прочитать
    код/файл (EVOL-SRC)."""

    search: bool = False
    verify: bool = False
    read_source: bool = False
    #: план L1 просит перепроверить раньше прочитанное (только ДОБАВЛЯЕТ
    #: проверку: снимает reuse, не понижает ``required``, не создаёт
    #: ``skip_reason``). Инициативный ход значение игнорирует.
    recheck: bool = False

    @property
    def any(self) -> bool:
        return bool(self.search or self.verify or self.read_source
                    or self.recheck)


@dataclass(frozen=True)
class SuppliedSources:
    """Уже поданные источники и детерминированные свойства реплики.

    ``verified_reuse`` — claim-key, для которых в этом ходе есть СВЕЖИЙ
    прочитанный источник (источник, а не ответ бота; см. §3). Пустое
    множество → reuse не засчитывается (обычный fetch)."""

    text: str = ""
    urls: tuple[str, ...] = ()
    media: bool = False
    files: bool = False
    #: реплика ТОЛЬКО трансформирует поданный текст (пересказ/перевод/правка)
    transformed_only: bool = False
    #: план пересказывает чат/память/саммари с атрибуцией (чужие слова)
    attributed_only: bool = False
    #: ответ уже есть в истории чата (спросили «что было в чате»)
    history_answer: bool = False
    verified_reuse: frozenset[str] = frozenset()

    def reuse_covers(self, claims) -> bool:
        """Все claim покрыты свежим verified-reuse источником?"""
        keys = [c.key() for c in (claims or ()) if getattr(c, "complete", False)]
        if not keys or not self.verified_reuse:
            return False
        return all(k in self.verified_reuse for k in keys)


@dataclass(frozen=True)
class RuntimeState:
    """Состояние хода, влияющее на класс (не на «разрешение» — см. allowed)."""

    effective_route: str = ""          # "provider/model" фактического вызова
    self_status_question: bool = False
    reuse_enabled: bool = True
    user_forbids_external: bool = False
    #: ход БЕЗ входящей реплики (инициатива/casual-продолжение): единственный
    #: возможный поисковый запрос — claim-key плана (§2.1 `claims_query`).
    #: Для Direct значение ``False``: там есть текст пользователя, и §1.2 п.8
    #: («неизвестно → проверка требуется») действует в полную силу.
    initiative: bool = False
    #: policy kill-switch: OFF → прежнее поведение (решение «не требуется»)
    enabled: bool = True


@dataclass(frozen=True)
class EvidenceContext:
    """Снимок разрешений для :func:`allowed` (§1.5, порядок фиксирован).

    Заполняется вызывающим из существующих источников:
    RBAC/чат-доступ — ``permissions``/``chat_access``; флаги сети —
    ``hot.get("flags.search_enabled", settings.SEARCH_ENABLED)`` и
    ``flags.webpage_enabled``; доступность — ``capability_registry.resolve``;
    квоты — ``tool_loop.METERED_TOOLS`` + ``budget_gate``/``mca_money_limits``;
    SSRF/размер/тип — ``safe_fetch`` (класс A, здесь только результат)."""

    rbac_ok: bool = True
    privacy_ok: bool = True
    user_forbids_external: bool = False
    #: capability → разрешена ли реальная сеть (глобальный/чатовый флаг)
    network_allowed: dict[str, bool] = field(default_factory=dict)
    #: capability → (ok, code) от `capability_registry.resolve`
    capabilities: dict[str, tuple[bool, str]] = field(default_factory=dict)
    #: capability → сетевой адрес прошёл SSRF-проверку (safe_fetch)
    ssrf_ok: dict[str, bool] = field(default_factory=dict)
    #: capability → квота/стоимость позволяет вызов
    quota_ok: dict[str, bool] = field(default_factory=dict)

    def state_of(self, capability: str) -> tuple[bool, str]:
        value = self.capabilities.get(str(capability or "").strip().lower())
        if value is None:
            return (False, BLOCK_CAPABILITY_NOT_READY)
        if isinstance(value, tuple):
            ok, code = value
            return (bool(ok), str(code or ""))
        return (bool(value), "" if value else BLOCK_PROVIDER_UNAVAILABLE)


@dataclass(frozen=True)
class EvidenceDecision:
    """Один выход политики (§1.1) + аддитивные машинные поля интеграции."""

    required: bool
    evidence_class: EvidenceClass = "externally_factual"
    claims: tuple[ClaimKey, ...] = ()
    source_kind: str = ""
    skip_reason: EvidenceSkipReason | None = None
    explicit_request: bool = False
    note: str = ""
    #: аддитивно (§2.1): read-only capabilities, обязательные для хода
    required_caps: tuple[str, ...] = ()
    #: аддитивно (§1.2 п.10): обязательная проверка не выполнена + причина
    failure_code: EvidenceFailureCode | None = None
    required_unmet: bool = False
    #: коды отказа `allowed()` по каждой требуемой capability (наблюдаемость)
    blocked: tuple[tuple[str, str], ...] = ()

    @property
    def network_calls(self) -> int:
        """Политика сама сетевых вызовов не делает (всегда 0)."""
        return 0

    def skip_code(self, *, found: bool = True) -> str:
        return skip_reason_code(self.skip_reason, found=found) \
            if self.skip_reason is not None else ""

    def event_fields(self, *, found: bool = True) -> dict:
        """R17-safe поля события ``EVIDENCE_POLICY_DECIDED`` (§4.5)."""
        reason = ""
        if self.failure_code is not None:
            reason = failure_reason_code(self.failure_code)
        elif self.skip_reason is not None:
            reason = skip_reason_code(self.skip_reason, found=found)
        return {
            "required": bool(self.required),
            "required_unmet": bool(self.required_unmet),
            "evidence_class": str(self.evidence_class),
            "skip_reason": (self.skip_reason.value
                            if self.skip_reason is not None else ""),
            "failure_code": (self.failure_code.value
                             if self.failure_code is not None else ""),
            "claim_count": len(self.claims),
            "source_kind": str(self.source_kind or ""),
            "required_caps": ",".join(self.required_caps),
            "network_calls": 0,
            "note": str(self.note or ""),
            "reason_code": reason,
        }


# ── §1.5: единственная точка разрешения ─────────────────────────────────────


def allowed(capability: str, ctx: EvidenceContext | None
            ) -> tuple[bool, str]:
    """``(ok, code)``: можно ли ходу исполнить read-only capability.

    Порядок проверок — контракт (§1.5): RBAC/доступ → запрет сети →
    доступность провайдера/ключа/состояния → стоимость/квота → SSRF →
    privacy. ``runtime_required`` не понижается confidence/tool_policy/
    execution_mode — это забота вызывающего; здесь решается только
    «разрешено ли технически». Никогда не бросает."""
    cap = str(capability or "").strip().lower()
    if not cap:
        return (False, BLOCK_CAPABILITY_NOT_READY)
    if ctx is None:
        # Контекста нет (чистая проверка класса) → разрешение не заявляем.
        return (False, BLOCK_CAPABILITY_NOT_READY)
    try:
        # 1. RBAC/доступ чата.
        if not ctx.rbac_ok:
            return (False, BLOCK_RBAC)
        # 2. Запрет сети: глобальный/чатовый флаг ИЛИ явный запрет в реплике.
        if ctx.user_forbids_external:
            return (False, BLOCK_EXTERNAL_DISABLED)
        network = ctx.network_allowed.get(cap)
        if network is False:
            return (False, BLOCK_EXTERNAL_DISABLED)
        # 3. Реальная доступность провайдера/ключа/состояния.
        ok, code = ctx.state_of(cap)
        if not ok:
            return (False, code or BLOCK_PROVIDER_UNAVAILABLE)
        # 4. Стоимость/квоты действующих лимитов.
        quota = ctx.quota_ok.get(cap)
        if quota is False:
            return (False, BLOCK_QUOTA)
        # 5. SSRF/размер/тип контента (safe_fetch — класс A, здесь результат).
        ssrf = ctx.ssrf_ok.get(cap)
        if ssrf is False:
            return (False, BLOCK_SSRF)
        # 6. Privacy/деперсонализация запроса.
        if not ctx.privacy_ok:
            return (False, BLOCK_PRIVACY)
        return (True, "")
    except Exception:      # pragma: no cover - защитная ветка
        return (False, BLOCK_CAPABILITY_NOT_READY)


def effective_capabilities(l1_requested, runtime_required, ctx,
                           *, skip_l1=()) -> tuple[tuple[str, ...],
                                                   tuple[tuple[str, str], ...]]:
    """``effective_readonly = allowed(L1_requested ∪ runtime_required)``.

    Возврат ``(effective, blocked)``: ``effective`` — упорядоченный union
    (сначала L1, затем runtime-обязательные) без отказов;
    ``blocked`` — ``((capability, code), ...)`` с наблюдаемой причиной
    (никогда не молчаливое удаление). Никогда не бросает."""
    effective: list[str] = []
    blocked: list[tuple[str, str]] = []
    seen: set[str] = set()
    skip = {str(c or "").strip().lower() for c in (skip_l1 or ())
            if str(c or "").strip()}
    for raw in list(l1_requested or ()) + list(runtime_required or ()):
        cap = str(raw or "").strip().lower()
        if not cap or cap in seen:
            continue
        seen.add(cap)
        if cap in skip:
            blocked.append((cap, "low_confidence"))
            continue
        ok, code = allowed(cap, ctx)
        if ok:
            effective.append(cap)
        else:
            blocked.append((cap, code or BLOCK_CAPABILITY_NOT_READY))
    return (tuple(effective), tuple(blocked))


# ── §1.2: правила вывода (порядок — контракт) ───────────────────────────────

_ACTION_SILENT = "silent"
_ACTION_REACT = "react"

#: Узкий детерминированный детектор вопроса о СВОЁМ состоянии (не словарь
#: инцидентных формулировок: только «о себе» + предмет состояния).
_SELF_SUBJECT_RE = re.compile(
    r"(?:\bты\b|\bтвой\b|\bтвоя\b|\bтвои\b|\bу тебя\b|\bтебе\b|\bбот\b|"
    r"\bтобой\b|\bсебя\b|\bсам\b)", re.IGNORECASE)
_SELF_SUBJECT_EN_RE = re.compile(
    r"\b(you|your|yourself)\b", re.IGNORECASE)
#: Предмет собственного состояния. «Железо/запуск» добавлены узко (сценарий
#: 13: «на каком железе ты это запускал?») — только вместе с субъектом «о
#: себе», поэтому технический вопрос о железе у собеседника не задевается.
_SELF_STATE_RE = re.compile(
    r"(модел\w*|движок|движк\w*|провайдер\w*|api[- ]?ключ\w*|"
    r"какой\w* (?:ты|модель)|на ч[её]м работа\w*|"
    r"желез\w*|на ч[её]м (?:ты\s+)?запуск\w*|запуска\w*|"
    r"верси\w* бота|какая верси\w*|"
    r"\bmodel\b|\bllm\b|\bprovider\b|\bengine\b|which model)", re.IGNORECASE)


def is_runtime_self_question(text) -> bool:
    """Вопрос о собственной модели/провайдере/состоянии (§1.2 п.5).

    Детерминированно и узко: нужен и субъект «о себе», и предмет состояния.
    «Какая модель лучше для игр?» — не про бота (субъекта «ты» нет)."""
    body = str(text or "")
    if not body.strip():
        return False
    has_subject = bool(_SELF_SUBJECT_RE.search(body)
                       or _SELF_SUBJECT_EN_RE.search(body))
    return bool(has_subject and _SELF_STATE_RE.search(body))


def _plan_attr(plan, name, default=None):
    try:
        return getattr(plan, name, default)
    except Exception:      # pragma: no cover - защитная ветка
        return default


def _required_caps_for(explicit: ExplicitRequest, *, claims, supplied,
                       evidence_class: str) -> tuple[str, ...]:
    """Read-only capabilities, обязательные для этого класса (§1.2/§2.1)."""
    if explicit.read_source:
        return (CAPABILITY_SOURCE_READ,)
    if explicit.verify:
        # «проверь это» — read-only внешняя сверка. Исполнитель — существующий
        # tool-путь (web); фактчек-вердикт остаётся за FC-полосой и
        # запрашивается ТОЛЬКО самим L1-планом (второго preflight/verdict
        # здесь не появляется, §2.4).
        return ("web_search",)
    if explicit.search or explicit.recheck:
        urls = tuple(supplied.urls or ())
        return ("fetch_url", "web_search") if urls else ("web_search",)
    if evidence_class == "externally_factual":
        urls = tuple(supplied.urls or ())
        return ("fetch_url", "web_search") if urls else ("web_search",)
    return ()


def evaluate_evidence_need(*, plan, task_kind: str,
                           explicit: ExplicitRequest | None = None,
                           supplied: SuppliedSources | None = None,
                           runtime_state: RuntimeState | None = None,
                           context: EvidenceContext | None = None
                           ) -> EvidenceDecision:
    """Нужна ли ходу внешняя read-only проверка (§1.2, порядок — контракт).

    Класс выводится из ПЛАНИРУЕМОГО содержания ответа. ``context``
    опционален: без него проверка доступности не выполняется (чистый
    класс-тест); с ним обязательные capabilities фильтруются через
    :func:`allowed` и отказ даёт ``failure_code`` (не исключение).

    Никогда не бросает: любая внутренняя ошибка → проверка требуется
    (асимметрия §1.2 п.8: пропуск обязательной проверки опаснее лишнего
    запроса)."""
    explicit = explicit or ExplicitRequest()
    supplied = supplied or SuppliedSources()
    runtime_state = runtime_state or RuntimeState()
    try:
        return _evaluate(plan=plan, task_kind=str(task_kind or ""),
                         explicit=explicit, supplied=supplied,
                         runtime_state=runtime_state, context=context)
    except Exception:      # pragma: no cover - защитная ветка
        return EvidenceDecision(required=True, evidence_class="externally_factual",
                                note="policy_error_requires_check")


def _evaluate(*, plan, task_kind, explicit, supplied, runtime_state,
              context) -> EvidenceDecision:
    if not runtime_state.enabled:
        # Kill-switch OFF: решение «проверка не требуется» (байт-паритет
        # прежнего поведения); класс фиксируется для наблюдаемости.
        return EvidenceDecision(required=False, evidence_class="background",
                                note="policy_disabled")
    # 1. SILENT/REACT — участие решено ДО tool-фазы (§1.2 п.1).
    action = str(_plan_attr(plan, "action", "reply") or "reply").lower()
    if action in (_ACTION_SILENT, _ACTION_REACT):
        return EvidenceDecision(
            required=False, evidence_class="social",
            skip_reason=EvidenceSkipReason.SILENT_OR_REACT_ONLY,
            note="participation_without_text")
    claims = classify_claims(plan)
    act = str(_plan_attr(plan, "response_act", "other") or "other")
    structure = str(_plan_attr(plan, "structure", "chat") or "chat")
    # 2. Явное поручение — независимо от confidence/tool_policy/mode
    #    (снимает C1/C2 на уровне решения).
    #    Инициативный ход (нет входящей реплики) не несёт просьбы человека:
    #    `recheck` плана там игнорируется (решение Architect «г», §5.2) —
    #    остальные сигналы не меняются.
    if runtime_state.initiative:
        explicit = replace(explicit, recheck=False)
    if explicit.any:
        kind = ("source_code" if explicit.read_source
                else ("web" if explicit.search or explicit.verify else "web"))
        caps = _required_caps_for(explicit, claims=claims,
                                 supplied=supplied,
                                 evidence_class="externally_factual")
        return _with_allowed(
            EvidenceDecision(required=True, evidence_class="externally_factual",
                             claims=claims, source_kind=kind,
                             explicit_request=True, required_caps=caps,
                             note=("explicit_read_source"
                                   if explicit.read_source
                                   else ("explicit_verify" if explicit.verify
                                         else ("explicit_search"
                                               if explicit.search
                                               else "plan_recheck")))),
            context=context, runtime_state=runtime_state)
    # 3. Только трансформация поданного текста — внешнего claim нет.
    if supplied.transformed_only and not claims:
        return EvidenceDecision(
            required=False, evidence_class="transformation",
            skip_reason=EvidenceSkipReason.TEXT_TRANSFORM_OR_TRANSLATION,
            note="transform_only")
    # 4. Атрибуция/история: пересказ чужих слов или ответ из истории чата.
    if supplied.history_answer:
        return EvidenceDecision(
            required=False, evidence_class="historical", claims=claims,
            source_kind="chat_history",
            skip_reason=EvidenceSkipReason.SUFFICIENT_CHAT_HISTORY_SOURCE,
            note="chat_history_has_answer")
    if supplied.attributed_only and not claims:
        return EvidenceDecision(
            required=False, evidence_class="attributed",
            source_kind="chat_history",
            skip_reason=EvidenceSkipReason.ATTRIBUTED_HISTORY_OR_SUMMARY,
            note="attributed_retelling")
    # 5. Собственная модель/настройки/состояние — runtime-источник есть.
    if runtime_state.self_status_question:
        return EvidenceDecision(
            required=False, evidence_class="runtime", claims=claims,
            source_kind="runtime",
            skip_reason=EvidenceSkipReason.SUFFICIENT_RUNTIME_SOURCE,
            note="runtime_route_source")
    # 6. Планируемое содержание несёт внешний факт.
    #    Инициативный ход БЕЗ входящей реплики — отдельная ветка ТОЛЬКО для
    #    нефактических актов: адресного запроса у него нет вовсе, единственный
    #    его источник — claim-key плана (§2.1 `claims_query`). План без
    #    claim'ов → проверять нечего; служебная формулировка цели («напомнить
    #    про релиз 1017») в сеть не уходит.
    #    Для ФАКТИЧЕСКИХ актов (`answer`/`explanation`/…) ветка НЕ действует:
    #    инициатива отвечает по тем же правилам, что Direct (§5.2, сценарий
    #    29), — проверка требуется, а отсутствие адресного запроса честно
    #    помечается `mark_required_unmet` в preflight (в сеть при этом не
    #    уходит ни один запрос: `claims_query` пуст).
    #    Для Direct ветка не действует никогда: там есть текст пользователя,
    #    поэтому §1.2 п.8 («неизвестно → проверка требуется») работает в
    #    полную силу.
    if runtime_state.initiative and not claims and act not in FACTUAL_ACTS:
        return EvidenceDecision(
            required=False, evidence_class="social", claims=claims,
            skip_reason=EvidenceSkipReason.NO_NEW_EXTERNAL_CLAIM,
            note="initiative_without_claim_query")
    factual = bool(claims) or act in FACTUAL_ACTS \
        or structure in FACTUAL_STRUCTURES \
        or str(task_kind or "") in ("explanation", "research", "comparison")
    if factual:
        # 9. Свежий claim-bound источник уже есть → reuse (не Smart Cache).
        if claims and runtime_state.reuse_enabled \
                and supplied.reuse_covers(claims):
            return EvidenceDecision(
                required=False, evidence_class="externally_factual",
                claims=claims, source_kind="web",
                skip_reason=EvidenceSkipReason.QUALIFIED_VERIFIED_REUSE,
                required_caps=(), note="verified_reuse")
        caps = _required_caps_for(explicit, claims=claims,
                                 supplied=supplied,
                                 evidence_class="externally_factual")
        return _with_allowed(
            EvidenceDecision(
                required=True, evidence_class="externally_factual",
                claims=claims,
                source_kind=("web" if "web_search" in caps or "fetch_url" in caps
                             else ""),
                required_caps=caps,
                note=("external_claims" if claims else "factual_plan_act")),
            context=context, runtime_state=runtime_state)
    # 7. Социально-творческие акты без внешнего claim (§1.2 п.7). Класс
    #    берётся из АКТА ПЛАНА, не из темы входящего текста и не из
    #    task_kind: пересказ технической темы шуткой внешней проверки не
    #    требует (§1.2 п.7/ТЗ §4.3).
    if act in SOCIAL_ACTS:
        return EvidenceDecision(
            required=False, evidence_class="social", claims=claims,
            skip_reason=EvidenceSkipReason.PURE_SOCIAL_OR_CREATIVE,
            note="social_act")
    # 7b. Убран (review-fix 3): правило было ГЛОБАЛЬНЫМ и гасило §1.2 п.8 для
    #     Direct — план `response_act=other` + `tool_policy=none` без claim'ов
    #     получал «проверка не требуется», хотя содержания мы просто не знаем.
    #     Его законная часть (инициатива без claim'ов) перенесена в правило 6 и
    #     срабатывает ТОЛЬКО при `runtime_state.initiative`.
    # 8. Неизвестно → проверка требуется (осознанная асимметрия).
    #    Для деградированного плана (LLM не ответил) содержания нет вовсе:
    #    класс берём из детерминированных сигналов — без сигнала внешнего
    #    утверждения проверять нечего (иначе каждый сбой планировщика
    #    оплачивал бы сетевой запрос).
    degraded = str(_plan_attr(plan, "source", "llm") or "llm") == "fallback"
    if degraded and not claims and not explicit.any:
        return EvidenceDecision(
            required=False, evidence_class="social", claims=claims,
            skip_reason=EvidenceSkipReason.NO_NEW_EXTERNAL_CLAIM,
            note="degraded_plan_without_signal")
    return _with_allowed(
        EvidenceDecision(required=True, evidence_class="externally_factual",
                         claims=claims, source_kind="web",
                         required_caps=("web_search",),
                         note="unknown_requires_check"),
        context=context, runtime_state=runtime_state)


def _with_allowed(decision: EvidenceDecision, *, context, runtime_state
                  ) -> EvidenceDecision:
    """Применить :func:`allowed` к обязательным capabilities (§1.2 п.10).

    ``context is None`` — разрешений нет (класс-тест/первый проход): решение
    возвращается как есть, `required_caps` НЕ схлопываются (иначе второй
    проход с реальным контекстом уже нечего проверять).

    Различаются два исхода:
    * **законный skip** — сеть запрещена (рубильник «Модуль Поиск»/`webpage`
      или явный запрет пользователя в реплике): это не «проверка сорвалась», а
      нормальное основание её не делать (§1.4 ``USER_FORBIDS_EXTERNAL``);
    * **не выполнено** — провайдер/ключ/квота/SSRF/privacy: обязательная
      проверка есть, но технически невозможна (`failure_code`, §1.2 п.10)."""
    if not decision.required_caps or not decision.required:
        return decision
    if context is None:
        return decision
    if runtime_state.user_forbids_external:
        # Явный запрет пользователя в самой реплике — нормальное основание
        # не делать внешний вызов (не сбой): тот же код, что у рубильника.
        blocked = tuple((cap, BLOCK_EXTERNAL_DISABLED)
                        for cap in decision.required_caps)
        return EvidenceDecision(
            required=False, evidence_class=decision.evidence_class,
            claims=decision.claims, source_kind="",
            explicit_request=decision.explicit_request, required_caps=(),
            skip_reason=EvidenceSkipReason.USER_FORBIDS_EXTERNAL,
            note=((decision.note + "+user_forbids") if decision.note
                  else "user_forbids"),
            blocked=blocked)
    effective, blocked = effective_capabilities(
        (), decision.required_caps, context)
    if effective:
        return EvidenceDecision(
            required=True, evidence_class=decision.evidence_class,
            claims=decision.claims, source_kind=decision.source_kind,
            explicit_request=decision.explicit_request,
            required_caps=effective, note=decision.note, blocked=blocked)
    if blocked and all(code == BLOCK_EXTERNAL_DISABLED for _c, code in blocked):
        # Ни одного разрешённого канала, и причина у ВСЕХ — запрет сети:
        # честный skip с наблюдаемым кодом `disabled`, а не «не выполнено».
        return EvidenceDecision(
            required=False, evidence_class=decision.evidence_class,
            claims=decision.claims, source_kind="",
            explicit_request=decision.explicit_request, required_caps=(),
            skip_reason=EvidenceSkipReason.USER_FORBIDS_EXTERNAL,
            note=((decision.note + "+user_forbids") if decision.note
                  else "user_forbids"),
            blocked=blocked)
    # Ни один нужный read-only tool не разрешён → обязательная проверка
    # НЕ выполнена честным кодом (не «пропускаем», §1.2 п.10).
    failure = None
    for _cap, code in blocked:
        if code == BLOCK_EXTERNAL_DISABLED:
            failure = EvidenceFailureCode.NETWORK_UNAVAILABLE
        elif code == BLOCK_QUOTA:
            failure = EvidenceFailureCode.QUOTA_EXHAUSTED
        elif code in (BLOCK_PROVIDER_UNAVAILABLE, BLOCK_PROVIDER_UNCONFIGURED,
                      BLOCK_TOOL_ABSENT):
            failure = EvidenceFailureCode.CAPABILITY_NOT_READY
        elif code == BLOCK_SSRF:
            failure = EvidenceFailureCode.SOURCE_FETCH_FAILED
        if failure is not None:
            break
    return EvidenceDecision(
        required=True, evidence_class=decision.evidence_class,
        claims=decision.claims, source_kind=decision.source_kind,
        explicit_request=decision.explicit_request, required_caps=(),
        note=(decision.note + "+blocked") if decision.note else "blocked",
        failure_code=failure or EvidenceFailureCode.CAPABILITY_NOT_READY,
        required_unmet=True, blocked=blocked)


def mark_required_unmet(decision, *,
                        code: EvidenceFailureCode | None = None,
                        note: str = "no_addressable_query"
                        ) -> EvidenceDecision:
    """Обязательная проверка есть, но адресного запроса у хода нет (§1.2 п.10).

    Единственный такой случай — инициативный ход без входящей реплики, план
    которого не дал ни одного claim-key: адресовать запрос некуда, а служебная
    формулировка цели («напомнить про релиз 1017») в поисковик не уходит
    (§2.1/§7 ТЗ). Это НЕ «проверка выполнена»: решение остаётся
    ``required=True``, помечается ``required_unmet`` с наблюдаемым кодом, а
    Writer получает честную подсказку «не утверждай, что проверил».
    Никогда не бросает."""
    if decision is None:
        return decision
    try:
        if not decision.required:
            return decision
        return replace(
            decision, required_caps=(), source_kind="", required_unmet=True,
            failure_code=(code or EvidenceFailureCode.NO_RELEVANT_RESULTS),
            note=((str(decision.note) + "+" + note) if decision.note else note))
    except Exception:      # pragma: no cover - защитная ветка
        return decision


def delivered_claim_keys(decision: EvidenceDecision, evidence_text) -> tuple:
    """Claim-key, которые РЕАЛЬНО подтверждены доставленной выдержкой.

    ``source_fetched ≠ delivered``: ключ засчитывается только если сущность
    claim присутствует в тексте пакета Writer'а (канон —
    ``claim_envelope.normalize_proposition``)."""
    body = _canon(evidence_text)
    if not body or decision is None:
        return ()
    out: list[str] = []
    for claim in (decision.claims or ()):
        if claim.complete and claim.entity and claim.entity in body:
            out.append(claim.key())
    return tuple(out)


def claims_coverage(decision: EvidenceDecision, delivered_keys) -> dict:
    """Машинная coverage-строка для пакета/события (§4.5).

    ``source_fetched ≠ evidence_delivered_to_writer``: параметр — ключи,
    которые РЕАЛЬНО доставлены в пакет Writer'а."""
    required = [c.key() for c in (decision.claims or ())]
    delivered = {str(k or "") for k in (delivered_keys or ()) if k}
    covered = [k for k in required if k in delivered]
    return {
        "required_claim_keys": required,
        "covered": covered,
        "missing": [k for k in required if k not in delivered],
    }


# ── §2.3: bounded outbound guard (egress) ───────────────────────────────────

GUARD_NONE = "none"
GUARD_HINT_RETRY = "hint_retry"
GUARD_ONE_LOOKUP = "one_lookup_then_hint_retry"
GUARD_DROP_CLAIM = "drop_unsupported_high_risk_claim"

GUARD_ACTIONS = (GUARD_NONE, GUARD_HINT_RETRY, GUARD_ONE_LOOKUP,
                 GUARD_DROP_CLAIM)

#: Классы повышенного риска (§2.3): существование/версия/цена/дата/число/
#: характеристика/категорическое опровержение. Метафора и чужая
#: атрибутированная речь сюда НЕ попадают (детерминированно).
_RISK_EXISTENCE_RE = re.compile(
    r"(не существует|не существовал\w*|не выпуска\w*|не выпущен\w*|"
    r"ещё не выш\w*|еще не выш\w*|не выходил\w*|не анонсир\w*|"
    r"не продаётся|не продается|снят\w* с производств\w*|"
    r"никогда не (?:было|существовал\w*|выпуска\w*)|"
    r"doesn'?t exist|does not exist|never existed|not released|"
    r"discontinued|опровергнут\w*|это фейк)", re.IGNORECASE)
_RISK_VERSION_RE = re.compile(
    # Версия — это ЛИБО слово-контекст («версия/version/v» + номер), ЛИБО
    # минимум три компонента (1.2.3). Голое «1.5» версия НЕ обозначает:
    # «потратил 1.5 часа» — обычная арифметика в болтовне, а не claim о
    # существовании/релизе (иначе guard глушил бы социальные реплики).
    r"\b(?:верси\w*|version|v)\s*\d+(?:\.\d+)+|\b\d+\.\d+\.\d+(?:\.\d+)*\b",
    re.IGNORECASE)
#: Голый год сам по себе НЕ высокий риск (обычная дата в болтовне); риск —
#: только вместе с событием/релизом/ценой (см. :func:`_high_risk`).
_RISK_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_RISK_EVENT_RE = re.compile(
    r"(выйдет|выйти|вышл\w*|выпуст\w*|релиз\w*|анонсир\w*|"
    r"стóит|стоит|цена|цены|появит\w*|запуст\w*|представ\w*|"
    r"release[sd]?|launch\w*|price[sd]?|announce\w*)", re.IGNORECASE)
_RISK_MONTH_RE = re.compile(
    r"\b(?:январ\w*|феврал\w*|март\w*|апрел\w*|ма[йя]\w*|июн\w*|июл\w*|"
    r"август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)\b|"
    r"\b(january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\b", re.IGNORECASE)
_RISK_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|гб|мб|тб|ггц|мгц|"
                             r"вт|втч|мп|мпикс|дюйм\w*|мм|см|кг|грамм\w*|"
                             r"gb|tb|mb|ghz|mhz|w|inch\w*|mp|usd|eur|rub|"
                             r"руб\w*|доллар\w*|долл\.?|\$|€|₽)", re.IGNORECASE)
#: Явный запрет пользователя ходить в сеть (§1.5 п.2, C3).
_FORBID_EXTERNAL_RE = re.compile(
    r"(?:не\s+(?:ищи|искать|гугли|гуглить|пользуйся|используй|ходи|лезь)\w*"
    r"[^.!?\n]{0,40}?(?:интернет\w*|сет[ьи]|поиск\w*|поисковик\w*)|"
    r"без\s+(?:интернета|сети|поиска)|"
    r"не\s+надо\s+(?:искать|гуглить|проверять\s+в\s+интернете)|"
    r"don'?t\s+(?:search|browse|google)|no\s+(?:web|internet)\s+search)",
    re.IGNORECASE)
#: Чужая речь/цитата — вне проверки (§2.3: «чужая атрибутированная речь»).
_ATTRIBUTED_RE = re.compile(
    r"(говорил\w*|сказал\w*|писал\w*|утвержда\w*|по словам|пересказ\w*|"
    r"цитат\w*|мол,|дескать|по мнению|according to|said|claims?)",
    re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")


def _plan_claims_text(decision: EvidenceDecision | None) -> str:
    if decision is None:
        return ""
    parts: list[str] = []
    for claim in (decision.claims or ()):
        parts.append(" ".join(x for x in (claim.entity, claim.relation,
                                          claim.version, claim.date,
                                          claim.metric) if x))
    return " ".join(parts)


def claims_query(decision: EvidenceDecision | None, *, limit: int = 160) -> str:
    """Поисковый запрос ТОЛЬКО из claim'ов плана (не из служебной цели).

    У инициативного хода нет пользовательской реплики: запрос, собранный из
    внутренней формулировки цели («напомнить про релиз»), уводит поиск в
    служебный текст и тратит единственный сетевой вызов впустую. Запрос
    строится из полей claim'а (entity + version/metric/date); claim'ов нет →
    пустая строка, и вызывающий поиск не делает вовсе."""
    if decision is None:
        return ""
    parts: list[str] = []
    for claim in (getattr(decision, "claims", ()) or ()):
        fields = [str(getattr(claim, name, "") or "").strip()
                  for name in ("entity", "version", "metric", "date")]
        text = " ".join(x for x in fields if x)
        if text and text not in parts:
            parts.append(text)
    return " ".join(parts)[:max(1, int(limit))].strip()


def _high_risk(sentence: str) -> bool:
    """Предложение содержит проверяемый высокорисковый класс claim?

    Классы (§2.3): существование/отсутствие (категорически), версия,
    цена/характеристика с единицей, дата-событие. Год/месяц сам по себе
    риском не считается — только вместе с событием/релизом/ценой, иначе
    обычная дата в болтовне глушилась бы guard'ом."""
    if not sentence.strip():
        return False
    if _RISK_EXISTENCE_RE.search(sentence) or _RISK_VERSION_RE.search(sentence):
        return True
    if _RISK_NUMBER_RE.search(sentence):
        return True
    dated = bool(_RISK_YEAR_RE.search(sentence)
                 or _RISK_MONTH_RE.search(sentence))
    return bool(dated and _RISK_EVENT_RE.search(sentence))


def is_external_forbidden(text) -> bool:
    """Пользователь явно запретил внешние запросы («без интернета»)?"""
    return bool(_FORBID_EXTERNAL_RE.search(str(text or "")))


def is_attributed_speech(text) -> bool:
    """Чужая/пересказанная речь, а не собственный claim бота (§2.3/сц.14).

    Только существующие примитивы: маркеры репортажа (``говорил/сказал/по
    словам``) и ``claim_envelope.classify_speech_act`` (retell/quote)."""
    body = str(text or "")
    if not body.strip():
        return False
    if _ATTRIBUTED_RE.search(body):
        return True
    try:
        from services.claim_envelope import (SPEECH_ACT_QUOTE,
                                             SPEECH_ACT_RETELL,
                                             classify_speech_act)
        return classify_speech_act(body) in (SPEECH_ACT_QUOTE,
                                             SPEECH_ACT_RETELL)
    except Exception:      # pragma: no cover - защитная ветка
        return False


def _attributed(sentence: str) -> bool:
    """Чужая речь/цитата — вне egress-проверки (атрибуция не наша)."""
    return is_attributed_speech(sentence)


def _supported(sentence: str, evidence_text: str) -> bool:
    """Подтверждает ли РЕАЛЬНО доставленная выдержка это предложение.

    Используется существующий семантический примитив
    ``search_aggregator.claim_relevance`` (числа/единицы/направление), а не
    регулярка «всегда/не существует»."""
    body = str(evidence_text or "").strip()
    if not body:
        return False
    try:
        from services.search_aggregator import _numbers_in, claim_relevance
        verdict = claim_relevance(
            body, claim_text=sentence,
            metrics=tuple(sorted(_numbers_in(sentence))))
        return bool(verdict.strong) or (bool(verdict.displayable)
                                        and not verdict.number_mismatch
                                        and not verdict.opposite)
    except Exception:      # pragma: no cover - защитная ветка
        return False


@dataclass(frozen=True)
class EgressVerdict:
    """Детерминированное решение исходящей проверки (§2.3)."""

    action: str = GUARD_NONE
    sentence: str = ""
    claim_key: str = ""
    reason_code: str = ""
    note: str = ""

    @property
    def rewrite_allowed(self) -> bool:
        return self.action in (GUARD_HINT_RETRY, GUARD_ONE_LOOKUP)

    @property
    def lookup_allowed(self) -> bool:
        return self.action == GUARD_ONE_LOOKUP

    @property
    def drop_allowed(self) -> bool:
        return self.action == GUARD_DROP_CLAIM

    def event_fields(self) -> dict:
        return {
            "guard_action": self.action,
            "lookup_used": int(self.action == GUARD_ONE_LOOKUP),
            "retry_used": int(self.rewrite_allowed),
            "dropped_claim": int(self.action == GUARD_DROP_CLAIM),
            "reason_code": self.reason_code,
            "note": self.note,
        }


#: Классы, ответы которых НЕ являются собственным внешним claim бота (§1.2
#: п.3/4/5): guard для них не запускается вовсе.
#:
#: ``social`` и ``attributed`` здесь БОЛЬШЕ НЕТ (review fix 2): шутка и
#: пересказ чужой речи — самый удобный способ пронести НОВЫЙ выдуманный факт
#: («Кстати, модели GeForce RTX 9090 не существует», «Новая цена будет 700$»),
#: и класс-уровневый skip пропускал его без единой проверки. Доброкачественная
#: болтовня защищена самим детектором высокого риска (`_high_risk`): метафора,
#: арифметика вроде «1.5 часа» и дата без события не срабатывают.
#:
#: Оставлены классы, где своего внешнего утверждения не бывает по построению:
#: ``transformation`` (пересказ поданного текста), ``historical`` (ответ уже
#: есть в истории чата), ``runtime`` (фактический runtime-источник),
#: ``background`` (рубильник политики выключен — паритет прежнего поведения).
GUARD_SKIP_CLASSES = ("background", "transformation", "historical", "runtime")


def guard_egress(*, answer, decision: EvidenceDecision | None = None,
                 evidence_text: str = "", delivered_keys=(),
                 lookup_used: bool = False, retry_used: bool = False
                 ) -> EgressVerdict:
    """Неподтверждённый существенный внешний claim в готовом ответе (§2.3).

    Проверяются ТОЛЬКО высокорисковые предложения (существование/версия/
    цена/дата/число/характеристика/категорическое опровержение); метафора и
    мат — вне проверки, а чужая атрибутированная речь/цитата вырезается
    ПОПРЕДЛОЖЕНЧЕСКИ (``_attributed``): пересказ чужих слов не наш claim.
    Класс-уровневый skip (``GUARD_SKIP_CLASSES``) узкий: шутка (``social``) и
    пересказ (``attributed``) проверяются, потому что добавленный Writer'ом
    новый внешний факт — всё равно наш claim. Действия ограничены
    ``GuardAction``: максимум один адресный lookup и одна повторная генерация,
    затем детерминированное удаление только этого предложения (остальной текст
    — тон, шутка, ритм — сохраняется).

    ``source_fetched ≠ verified``: подтверждением считается лишь реально
    доставленная Writer'у выдержка (``evidence_text``), а не факт вызова
    инструмента. Никогда не бросает."""
    try:
        body = str(answer or "").strip()
        if not body:
            return EgressVerdict()
        if decision is not None:
            klass = str(getattr(decision, "evidence_class", "") or "")
            # Класс без собственного внешнего claim (§1.2 п.3/4/5) —
            # guard не применяется: проверять нечего.
            #
            # Флаг ``required`` здесь НЕ проверяется (review fix 2): решение
            # политики «проверка не требуется» относится к ПЛАНИРУЕМОМУ
            # содержанию, а guard смотрит УЖЕ написанный текст. Writer легко
            # добавляет новый внешний факт мимо плана — и в шутке, и в
            # атрибутированном пересказе (сценарии 16/24) — и именно его
            # обязан поймать ограниченный выходной guard.
            if klass in GUARD_SKIP_CLASSES:
                return EgressVerdict(note="not_externally_factual")
        planned = _plan_claims_text(decision)
        delivered = {str(k or "") for k in (delivered_keys or ()) if k}
        for sentence in _SENTENCE_SPLIT_RE.split(body):
            piece = str(sentence or "").strip()
            if len(piece) < 8 or not _high_risk(piece):
                continue
            if _attributed(piece):
                continue
            if _supported(piece, evidence_text):
                continue
            if planned and _supported(piece, planned):
                # Планируемый claim — часть плана, не «новая добавка Writer'а»;
                # но подтверждения в пакете нет → та же честная реакция.
                pass
            key = ""
            try:
                from services.search_aggregator import _numbers_in
                key = ",".join(sorted(_numbers_in(piece)))[:32]
            except Exception:      # pragma: no cover - защитная ветка
                key = ""
            if not lookup_used:
                return EgressVerdict(
                    action=GUARD_ONE_LOOKUP, sentence=piece[:240],
                    claim_key=key, note="unsupported_claim_lookup")
            if not retry_used:
                return EgressVerdict(
                    action=GUARD_HINT_RETRY, sentence=piece[:240],
                    claim_key=key, note="unsupported_claim_retry")
            return EgressVerdict(
                action=GUARD_DROP_CLAIM, sentence=piece[:240],
                claim_key=key, reason_code=REASON_EVIDENCE_CLAIM_REMOVED,
                note="unsupported_claim_dropped")
        return EgressVerdict()
    except Exception:      # pragma: no cover - защитная ветка
        return EgressVerdict()


def drop_claim_sentence(answer, sentence) -> str:
    """Детерминированно удалить ТОЛЬКО это предложение (§2.3).

    Остальной текст (шутка/ритм/метафора) сохраняется; пустой результат —
    честная тишина вызывающего, а не «данных недостаточно»."""
    body = str(answer or "")
    piece = str(sentence or "").strip()
    if not piece:
        return body
    out = body.replace(piece, "")
    if out == body:
        # Предложение с обрезанным хвостом/иной пунктуацией — ищем по началу.
        head = piece[:40]
        idx = body.find(head)
        if idx >= 0:
            out = body[:idx] + body[idx + len(piece):]
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


# ── §5.6: runtime-источник для вопроса о себе ───────────────────────────────


def runtime_source_note(effective_route: str, *, provider: str = "") -> str:
    """Машинная строка о ФАКТИЧЕСКОМ маршруте вызова (не о промпте).

    Нужна Writer'у, чтобы «на какой модели работаешь?» отвечался из
    существующего источника (фактический вызов), а не угадывался."""
    route = str(effective_route or "").strip()
    prov = str(provider or "").strip()
    if not route and not prov:
        return ""
    label = f"{prov}/{route}" if prov and route else (route or prov)
    return ("[RUNTIME] фактический маршрут этого ответа: "
            f"{label[:120]} (источник — реальный вызов, не промпт; "
            "не выдумывай модель/провайдера)")


# ── kill-switch (§8.2, паттерн mca_gates: env + ClassVar) ───────────────────

POLICY_GATE_ENV = "EVIDENCE_ROUTING_POLICY_ENABLED"
EGRESS_GATE_ENV = "EVIDENCE_EGRESS_GUARD_ENABLED"


def _flag(env_name: str, override: str | None, default: bool = True) -> bool:
    """env-флаг с ClassVar-override (None → env; иначе значение override)."""
    if override is not None:
        return bool(override)
    raw = os.getenv(env_name)
    if raw is None or not str(raw).strip():
        return bool(default)
    return str(raw).strip().lower() in ("1", "true", "on", "yes", "enabled")


#: ClassVar-переключатели (тесты/оператор): None → env, иначе явное значение.
POLICY_ENABLED_OVERRIDE: bool | None = None
EGRESS_ENABLED_OVERRIDE: bool | None = None


def policy_enabled() -> bool:
    """Политика обязательности read-only проверки включена?"""
    return _flag(POLICY_GATE_ENV, POLICY_ENABLED_OVERRIDE, True)


def egress_guard_enabled() -> bool:
    """Bounded outbound guard включён? OFF → прежнее поведение байт-в-байт."""
    return _flag(EGRESS_GATE_ENV, EGRESS_ENABLED_OVERRIDE, True)
