"""VMQ-ONTO-A (O-01, O-02) — типизированная read-only проекция семантического
значения памяти.

Источник: `plans/features/vmq-onto-01/architecture-onto-ab.md` (typed value
model, инварианты, приёмка O-01/O-02) и подтверждение
`evidence/onto-a-contract-confirmation-2026-11-15.md` (ARCH_REUSE_CONFIRMED).

**Что это.** Небольшой валидатор/проектор семантического значения поверх уже
существующих владельцев. Здесь нет второго resolver/router/search/LLM/store,
нет SQL, DDL и записи: проекция только читает переданные строки/результаты.

* типы — ровно CHECK `nodes.entity_type`: `user|topic|event|fact`
  (`memory_contracts.ENTITY_TYPES_ALLOWED`), derived meaning тип не расширяет;
* идентичность и неоднозначность — существующий
  `services.entity_resolver.resolve_entity` (UID-first, alias как hint,
  `ambiguous` без автовыбора); здесь только typed-оценка его результата;
* атрибуция «кто сказал / о ком» — `memory_contracts.EntityRef`,
  `EntityResolution`, `ResolutionCandidate`, `StatementAttribution`;
* provenance/verification — `graphrag_provenance.classify_fact_provenance`,
  `classify_origin_class` и `memory_contracts.OriginClass` (значения не
  дублируются);
* роли сообщения (author / reply / quote / forward) — `message_identity.roles`.

**Типизированные проверки (не строковое равенство).** Тип выводится из
`chat_scope` + наличия participant identity (Telegram UID) + времени события
(`event_time`) + statement provenance, а не из совпадения имени:

===========  ==============================================================
`user`       требуется participant identity → иначе это weak hint, не человек
`topic`      participant identity у самого референта запрещена (type conflict)
`event`      требуется time anchor (`event_time`) → иначе `tentative`
`fact`       требуется statement provenance (speaker/asserted_at)
===========  ==============================================================

**Alias — только hint.** Имя/алиас никогда не становится идентичностью: при
разрешении по имени/алиасу/casefold референс попадает в `hint_ref`, а
`canonical` остаётся `None` (личность подтверждает лишь participant identity).
Поэтому нарицательное имя, совпавшее с алиасом, и одинаковые display-имена
разных людей не превращаются в канонический объект «человек».

**Честный unknown.** Неизвестный/отсутствующий тип, роль, время или
provenance остаются `unknown`/`tentative` с явными `missing`/`degraded`;
`ambiguous` сохраняет `candidates` без выбранного canonical. `verified`
требует существующего provenance-контракта: цитата/репост, co-occurrence,
legacy-строка и собственный вывод бота `verified` не дают.

В этом срезе (ONTO-A) модуль не вызывается из retrieval: он предоставляет
контракт, который потребляет ONTO-B/M2. Никаких событий/логов с текстами
фактов, субъектов или запросов модуль не порождает (R17).
"""
from __future__ import annotations

import dataclasses
from typing import Any, Mapping

from services import graphrag_provenance as grp
from services import memory_contracts as mc
from services import provenance

__all__ = [
    # роли значения
    "ROLE_SPEAKER", "ROLE_SUBJECT", "MEANING_ROLES",
    # база идентичности
    "IDENTITY_BASIS_PARTICIPANT", "IDENTITY_BASIS_ADDRESS",
    "IDENTITY_BASIS_NAME_HINT", "IDENTITY_BASIS_NONE", "IDENTITY_BASES",
    # сигналы типа
    "TYPE_SIGNAL_CHAT_SCOPE", "TYPE_SIGNAL_PARTICIPANT_IDENTITY",
    "TYPE_SIGNAL_TIME_ANCHOR", "TYPE_SIGNAL_STATEMENT_PROVENANCE",
    "TYPE_SIGNALS", "REQUIRED_TYPE_SIGNALS",
    # reason/degraded коды
    "REASON_TYPE_UNKNOWN", "REASON_INVALID_ENTITY_TYPE",
    "REASON_CROSS_CHAT_SCOPE", "REASON_TYPE_CONFLICT",
    "REASON_TYPE_SIGNALS_INCOMPLETE", "REASON_PARTICIPANT_IDENTITY",
    "REASON_NODE_ADDRESS", "REASON_NAME_HINT_ONLY",
    "REASON_NAME_HINT_AMBIGUOUS", "REASON_IDENTITY_UNRESOLVED",
    "REASON_ROLE_UNRESOLVED", "DEGRADED_TYPE_SIGNALS_INCOMPLETE",
    "DEGRADED_IDENTITY_HINT_ONLY", "DEGRADED_IDENTITY_UNRESOLVED",
    "DEGRADED_ROLE_UNRESOLVED", "DEGRADED_PROVENANCE_NOT_CONFIRMED",
    "DEGRADED_CODES",
    # контролируемые значения статуса
    "VERIFIED", "TENTATIVE", "UNKNOWN", "REJECTED",
    # типы
    "TypedEntityType", "SemanticIdentity", "SemanticRole", "MeaningTime",
    "SemanticMeaning",
    # функции
    "classify_entity_type", "project_identity", "project_node_meaning",
    "project_fact_meaning",
]

# ── Контролируемые статусы: ровно `provenance.VERIFICATIONS` ───────────────
VERIFIED = "verified"
TENTATIVE = "tentative"
UNKNOWN = "unknown"
REJECTED = "rejected"

# ── Роли значения (закрытый набор; слоты не взаимозаменяемы) ────────────────
ROLE_SPEAKER = "speaker"      # кто произнёс/утверждает
ROLE_SUBJECT = "subject"      # о ком/о чём утверждение
MEANING_ROLES = frozenset({ROLE_SPEAKER, ROLE_SUBJECT})

# ── Чем именно установлена идентичность референта ──────────────────────────
#: Participant identity (Telegram UID / canonical ID) — единственная личность.
IDENTITY_BASIS_PARTICIPANT = "participant_identity"
#: Адрес существующей строки в chat scope (topic/event/fact node) — не личность.
IDENTITY_BASIS_ADDRESS = "node_address"
#: Имя/алиас/написание — только поисковая подсказка, НЕ идентичность.
IDENTITY_BASIS_NAME_HINT = "name_hint"
IDENTITY_BASIS_NONE = "none"
IDENTITY_BASES = frozenset({
    IDENTITY_BASIS_PARTICIPANT, IDENTITY_BASIS_ADDRESS,
    IDENTITY_BASIS_NAME_HINT, IDENTITY_BASIS_NONE,
})

# ── Сигналы, из которых выводится тип (не строковое равенство) ─────────────
TYPE_SIGNAL_CHAT_SCOPE = "chat_scope"
TYPE_SIGNAL_PARTICIPANT_IDENTITY = "participant_identity"
TYPE_SIGNAL_TIME_ANCHOR = "time_anchor"
TYPE_SIGNAL_STATEMENT_PROVENANCE = "statement_provenance"
TYPE_SIGNALS = frozenset({
    TYPE_SIGNAL_CHAT_SCOPE, TYPE_SIGNAL_PARTICIPANT_IDENTITY,
    TYPE_SIGNAL_TIME_ANCHOR, TYPE_SIGNAL_STATEMENT_PROVENANCE,
})

#: Обязательные сигналы каждого типа (пусто — достаточно chat scope).
REQUIRED_TYPE_SIGNALS: dict[str, tuple[str, ...]] = {
    "user": (TYPE_SIGNAL_PARTICIPANT_IDENTITY,),
    "topic": (),
    "event": (TYPE_SIGNAL_TIME_ANCHOR,),
    "fact": (TYPE_SIGNAL_STATEMENT_PROVENANCE,),
}

# ── Диагностические коды (не lexical-триггеры и не поведение) ───────────────
REASON_TYPE_UNKNOWN = "entity_type_unknown"
REASON_INVALID_ENTITY_TYPE = "invalid_entity_type"
REASON_CROSS_CHAT_SCOPE = "cross_chat_scope"
REASON_TYPE_CONFLICT = "type_conflict_single_slot"
REASON_TYPE_SIGNALS_INCOMPLETE = "type_signals_incomplete"
REASON_PARTICIPANT_IDENTITY = "participant_identity"
REASON_NODE_ADDRESS = "node_address"
REASON_NAME_HINT_ONLY = "name_hint_only"
REASON_NAME_HINT_AMBIGUOUS = "name_hint_ambiguous"
REASON_IDENTITY_UNRESOLVED = "identity_unresolved"
REASON_ROLE_UNRESOLVED = "role_unresolved"

DEGRADED_TYPE_SIGNALS_INCOMPLETE = "type_signals_incomplete"
DEGRADED_IDENTITY_HINT_ONLY = "identity_hint_only"
DEGRADED_IDENTITY_UNRESOLVED = "identity_unresolved"
DEGRADED_ROLE_UNRESOLVED = "role_unresolved"
DEGRADED_PROVENANCE_NOT_CONFIRMED = "provenance_not_confirmed"
DEGRADED_CODES = frozenset({
    DEGRADED_TYPE_SIGNALS_INCOMPLETE, DEGRADED_IDENTITY_HINT_ONLY,
    DEGRADED_IDENTITY_UNRESOLVED, DEGRADED_ROLE_UNRESOLVED,
    DEGRADED_PROVENANCE_NOT_CONFIRMED,
})

#: Классы provenance факта (значения существующего владельца, не копия).
_FACT_PROVENANCE_CLASSES = frozenset({
    grp.EDGE_CONFIDENT, grp.EDGE_TENTATIVE, grp.EDGE_LEGACY_UNVERIFIED,
})
#: Происхождение, которое вообще не подтверждает (соседство в реплике, §2.3).
_NON_CONFIRMING_ORIGINS = frozenset({mc.OriginClass.COOCCURRENCE})
#: Происхождение, которое может подтверждать утверждение источника.
_CONFIRMING_ORIGINS = frozenset({
    mc.OriginClass.EXPLICIT_DIRECT, mc.OriginClass.REPORTED_THIRD_PARTY,
})


# ── Мелкие типизированные границы (ValueError = ошибка контракта) ───────────

def _chat_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"chat_id must be int, got {type(value).__name__}")
    return int(value)


def _opt_ts(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or int(value) <= 0:
        raise ValueError(f"{field} must be a positive int or None")
    return int(value)


def _opt_id(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or int(value) <= 0:
        raise ValueError(f"{field} must be a positive int or None")
    return int(value)


def _entity_type(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("entity_type must be str or None")
    return value.strip()


def _mention(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:mc.ENTITY_MENTION_MAX_CHARS]


def _reason(value: Any) -> str:
    return str(value or "").strip()[:64]


def _status(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if text not in provenance.VERIFICATIONS:
        raise ValueError(
            f"{field} invalid: {text!r}; allowed: {sorted(provenance.VERIFICATIONS)}")
    return text


def _row_map(row: Any) -> dict:
    """Строка БД (`sqlite3.Row`, mapping) → обычный dict без изменения данных.

    Существующие владельцы (`graphrag_provenance`) читают `.get()`, поэтому
    `sqlite3.Row` приводится к dict здесь, а не внутри них.
    """
    if isinstance(row, Mapping):
        return dict(row)
    keys = getattr(row, "keys", None)
    if callable(keys):
        return {key: row[key] for key in keys()}
    raise ValueError("row must be a mapping or sqlite3.Row")


def _row_text(row: Mapping, key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _row_int(row: Mapping, key: str) -> int | None:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


def _same_chat(left: Any, right: Any) -> bool:
    try:
        return int(left) == int(right)
    except (TypeError, ValueError):
        return False


def _resolution_is_uid_proven(resolution: mc.EntityResolution) -> bool:
    """Резолв по устойчивой Telegram-идентичности (правило 1 владельца).

    Код причины берётся у существующего владельца (`entity_resolver`), второго
    правила «это UID» здесь нет. Недоступность владельца = консервативно «нет»:
    без доказанной идентичности alias остаётся hint.
    """
    try:
        from services import entity_resolver
    except Exception:                                     # pragma: no cover
        return False
    return _reason(resolution.reason_code) == entity_resolver.REASON_STABLE_IDENTITY


# ── Тип узла: типизированные сигналы, а не имя ─────────────────────────────

@dataclasses.dataclass(frozen=True)
class TypedEntityType:
    """Тип значения + чем именно он установлен (§typed value model).

    `status` — `verified` (все обязательные сигналы есть), `tentative`
    (часть сигналов отсутствует), `unknown` (сигналов нет вовсе) либо
    `rejected` (недопустимый тип / чужой chat scope / конфликт типа).
    `missing` перечисляет реально отсутствующие обязательные сигналы, поэтому
    «неизвестное» видно, а не додумывается.
    """

    entity_type: str | None
    status: str
    signals: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    reason_code: str = ""

    def __post_init__(self) -> None:
        status = _status(self.status, "TypedEntityType.status")
        entity_type = self.entity_type
        if entity_type is not None and not isinstance(entity_type, str):
            raise ValueError("TypedEntityType.entity_type must be str or None")
        signals = tuple(self.signals or ())
        missing = tuple(self.missing or ())
        for value in signals:
            if value not in TYPE_SIGNALS:
                raise ValueError(f"TypedEntityType.signals invalid: {value!r}")
        for value in missing:
            if value not in TYPE_SIGNALS:
                raise ValueError(f"TypedEntityType.missing invalid: {value!r}")
        if len(set(signals)) != len(signals):
            raise ValueError("TypedEntityType.signals contains duplicates")
        if len(set(missing)) != len(missing):
            raise ValueError("TypedEntityType.missing contains duplicates")
        if set(signals) & set(missing):
            raise ValueError(
                "TypedEntityType signal cannot be both present and missing")
        reason = _reason(self.reason_code)
        if status is VERIFIED and (missing or not signals):
            raise ValueError(
                "verified type requires all mandatory signals and none missing")
        if status is REJECTED and not reason:
            raise ValueError("rejected type requires reason_code")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "signals", signals)
        object.__setattr__(self, "missing", missing)
        object.__setattr__(self, "reason_code", reason)

    @property
    def is_typed(self) -> bool:
        """Тип установлен типизированными сигналами (не догадкой)."""
        return self.status == VERIFIED

    @property
    def is_unknown(self) -> bool:
        return self.status == UNKNOWN

    def as_dict(self) -> dict:
        return {
            "entity_type": self.entity_type,
            "status": self.status,
            "signals": list(self.signals),
            "missing": list(self.missing),
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TypedEntityType":
        return cls(
            entity_type=data.get("entity_type"),
            status=data.get("status", UNKNOWN),
            signals=tuple(data.get("signals") or ()),
            missing=tuple(data.get("missing") or ()),
            reason_code=data.get("reason_code") or "",
        )


def classify_entity_type(
    entity_type: Any,
    *,
    chat_id: Any = None,
    referent_chat_id: Any = None,
    has_participant_identity: bool = False,
    has_statement_provenance: bool = False,
    event_time: Any = None,
) -> TypedEntityType:
    """Тип значения по сигналам (§O-01), не по равенству строк.

    `chat_id` — scope референта; `referent_chat_id` — scope, из которого он
    фактически пришёл (несовпадение = `rejected/cross_chat_scope`).
    `has_participant_identity` — у САМОГО референта есть Telegram UID/canonical
    ID. `event_time` — время события (time anchor типа `event`).
    `has_statement_provenance` — утверждение атрибутировано (speaker/asserted_at).

    Неизвестный (пустой) тип → `unknown`; недопустимый (`person`, `entity`…)
    → `rejected/invalid_entity_type`, а не «новый тип» и не чужой тип.
    """
    chat_ok = isinstance(chat_id, int) and not isinstance(chat_id, bool)
    present: list[str] = []
    if chat_ok:
        present.append(TYPE_SIGNAL_CHAT_SCOPE)
    if has_participant_identity:
        present.append(TYPE_SIGNAL_PARTICIPANT_IDENTITY)
    event_ts = _opt_ts(event_time, "event_time")
    if event_ts is not None:
        present.append(TYPE_SIGNAL_TIME_ANCHOR)
    if has_statement_provenance:
        present.append(TYPE_SIGNAL_STATEMENT_PROVENANCE)
    present_t = tuple(present)

    text = _entity_type(entity_type)
    if not text:
        return TypedEntityType(
            entity_type=None, status=UNKNOWN, signals=present_t,
            missing=() if chat_ok else (TYPE_SIGNAL_CHAT_SCOPE,),
            reason_code=REASON_TYPE_UNKNOWN)
    if text not in mc.ENTITY_TYPES_ALLOWED:
        return TypedEntityType(
            entity_type=text, status=REJECTED, signals=present_t,
            reason_code=REASON_INVALID_ENTITY_TYPE)
    if referent_chat_id is not None and not _same_chat(chat_id, referent_chat_id):
        return TypedEntityType(
            entity_type=text, status=REJECTED, signals=present_t,
            reason_code=REASON_CROSS_CHAT_SCOPE)
    required = REQUIRED_TYPE_SIGNALS[text]
    if (text == "topic"
            and TYPE_SIGNAL_PARTICIPANT_IDENTITY in present_t):
        # Один слот имени на чат (§1.2.3): референт с participant identity —
        # человек, а не тема; молча менять тип запрещено.
        return TypedEntityType(
            entity_type=text, status=REJECTED, signals=present_t,
            missing=required, reason_code=REASON_TYPE_CONFLICT)
    missing = tuple(sig for sig in required if sig not in present_t)
    if not present_t:
        return TypedEntityType(
            entity_type=text, status=UNKNOWN, signals=present_t,
            missing=missing, reason_code=REASON_TYPE_UNKNOWN)
    if missing:
        return TypedEntityType(
            entity_type=text, status=TENTATIVE, signals=present_t,
            missing=missing, reason_code=REASON_TYPE_SIGNALS_INCOMPLETE)
    return TypedEntityType(
        entity_type=text, status=VERIFIED, signals=present_t, missing=())


# ── Идентичность референта: UID — identity, имя/алиас — hint ───────────────

@dataclasses.dataclass(frozen=True)
class SemanticIdentity:
    """Typed-оценка идентичности референта в одном chat scope.

    Разделены три разных вещи, которые нельзя склеивать:

    * `canonical` — подтверждённый адрес/личность (`participant_identity` —
      Telegram UID, либо `node_address` — строка topic/event/fact в scope);
    * `hint_ref` — референс, найденный по имени/алиасу/casefold: **подсказка**,
      не идентичность (поэтому у `user` при name hint `canonical is None`);
    * `candidates` — неоднозначность: canonical не выбран, вариантов ≥ 2.

    `mention` — исходный текст упоминания (display/диагностика), никогда не
    ключ идентичности. `participant_id` — существующий Telegram UID.
    """

    chat_id: int
    entity_type: str
    basis: str
    status: str
    participant_id: int | None = None
    canonical: mc.EntityRef | None = None
    hint_ref: mc.EntityRef | None = None
    candidates: tuple[mc.ResolutionCandidate, ...] = ()
    mention: str | None = None
    reason_code: str = ""

    def __post_init__(self) -> None:
        chat_id = _chat_id(self.chat_id)
        entity_type = _entity_type(self.entity_type)
        if not entity_type:
            raise ValueError("SemanticIdentity.entity_type must be non-empty")
        basis = str(self.basis or "").strip()
        if basis not in IDENTITY_BASES:
            raise ValueError(
                f"SemanticIdentity.basis invalid: {basis!r}; "
                f"allowed: {sorted(IDENTITY_BASES)}")
        status = _status(self.status, "SemanticIdentity.status")
        participant_id = _opt_id(self.participant_id,
                                 "SemanticIdentity.participant_id")
        mention = _mention(self.mention)
        reason = _reason(self.reason_code)

        canonical = self.canonical
        if canonical is not None and not isinstance(canonical, mc.EntityRef):
            raise ValueError("SemanticIdentity.canonical must be EntityRef")
        hint_ref = self.hint_ref
        if hint_ref is not None and not isinstance(hint_ref, mc.EntityRef):
            raise ValueError("SemanticIdentity.hint_ref must be EntityRef")
        candidates = tuple(self.candidates or ())
        seen: set[int] = set()
        for candidate in candidates:
            if not isinstance(candidate, mc.ResolutionCandidate):
                raise ValueError(
                    "SemanticIdentity.candidates[] must be ResolutionCandidate")
            if candidate.ref.node_id in seen:
                raise ValueError(
                    "SemanticIdentity.candidates contains duplicate refs")
            seen.add(candidate.ref.node_id)
        if candidates:
            if canonical is not None:
                raise ValueError(
                    "ambiguous identity must not pick a canonical entity (ID-8)")
            if len(candidates) < 2:
                raise ValueError(
                    "identity candidates require >= 2 variants (ID-8)")

        typed_scope_known = entity_type in mc.ENTITY_TYPES_ALLOWED
        for ref in (canonical, hint_ref):
            if ref is None:
                continue
            if not typed_scope_known:
                raise ValueError(
                    "identity ref requires a supported entity_type")
            if not _same_chat(ref.chat_id, chat_id):
                raise ValueError(
                    "identity ref must belong to the same chat (ID-2)")
            if ref.entity_type != entity_type:
                raise ValueError(
                    "identity ref must match the entity_type")
        for candidate in candidates:
            if not _same_chat(candidate.ref.chat_id, chat_id):
                raise ValueError(
                    "identity candidate must belong to the same chat (ID-2)")
            if candidate.ref.entity_type != entity_type:
                raise ValueError(
                    "identity candidate must match the entity_type")

        if not typed_scope_known and basis is not IDENTITY_BASIS_NONE:
            raise ValueError(
                "unsupported entity_type cannot claim an identity basis")
        if canonical is not None and basis not in (
                IDENTITY_BASIS_PARTICIPANT, IDENTITY_BASIS_ADDRESS):
            raise ValueError(
                "canonical identity requires participant_identity/node_address")
        if basis is IDENTITY_BASIS_NAME_HINT:
            if participant_id is not None:
                raise ValueError(
                    "name hint must not claim a participant identity")
            if status not in (TENTATIVE, UNKNOWN):
                raise ValueError(
                    "name hint is tentative/unknown, never verified")
            if status is TENTATIVE and hint_ref is None:
                raise ValueError("tentative name hint requires hint_ref")
        if basis is IDENTITY_BASIS_NONE:
            if canonical is not None or hint_ref is not None:
                raise ValueError(
                    "identity basis 'none' cannot carry refs")
        if status is VERIFIED:
            if basis not in (IDENTITY_BASIS_PARTICIPANT,
                             IDENTITY_BASIS_ADDRESS):
                raise ValueError(
                    "verified identity requires a proven basis")
            if participant_id is None and canonical is None:
                raise ValueError(
                    "verified identity requires participant_id or canonical")
        if status is TENTATIVE and hint_ref is None:
            raise ValueError("tentative identity requires hint_ref")
        if status is UNKNOWN and canonical is not None:
            raise ValueError("unknown identity must not carry canonical")
        if status is REJECTED:
            if canonical is not None or hint_ref is not None:
                raise ValueError("rejected identity must not carry refs")
            if not reason:
                raise ValueError("rejected identity requires reason_code")

        object.__setattr__(self, "chat_id", chat_id)
        object.__setattr__(self, "entity_type", entity_type)
        object.__setattr__(self, "basis", basis)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "participant_id", participant_id)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "mention", mention)
        object.__setattr__(self, "reason_code", reason)

    @property
    def is_identity_confirmed(self) -> bool:
        """Идентичность доказана (UID или адрес), а не подсказана именем."""
        return self.status == VERIFIED and self.basis in (
            IDENTITY_BASIS_PARTICIPANT, IDENTITY_BASIS_ADDRESS)

    @property
    def is_person_confirmed(self) -> bool:
        """Именно личность подтверждена participant identity (не адрес)."""
        return (self.status == VERIFIED
                and self.basis == IDENTITY_BASIS_PARTICIPANT)

    @property
    def is_ambiguous(self) -> bool:
        """Неоднозначность: есть варианты и НЕ выбран canonical."""
        return len(self.candidates) >= 2

    @property
    def is_hint_only(self) -> bool:
        """Имя/алиас: только подсказка, канонического объекта нет."""
        return self.basis == IDENTITY_BASIS_NAME_HINT

    def as_dict(self) -> dict:
        return {
            "chat_id": self.chat_id,
            "entity_type": self.entity_type,
            "basis": self.basis,
            "status": self.status,
            "participant_id": self.participant_id,
            "canonical": self.canonical.as_dict() if self.canonical else None,
            "hint_ref": self.hint_ref.as_dict() if self.hint_ref else None,
            "candidates": [c.as_dict() for c in self.candidates],
            "mention": self.mention,
            "identity_confirmed": self.is_identity_confirmed,
            "ambiguous": self.is_ambiguous,
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticIdentity":
        canonical = data.get("canonical")
        hint_ref = data.get("hint_ref")
        return cls(
            chat_id=data["chat_id"], entity_type=data["entity_type"],
            basis=data["basis"], status=data["status"],
            participant_id=data.get("participant_id"),
            canonical=mc.EntityRef.from_dict(canonical) if canonical else None,
            hint_ref=mc.EntityRef.from_dict(hint_ref) if hint_ref else None,
            candidates=tuple(mc.ResolutionCandidate.from_dict(c)
                             for c in data.get("candidates") or ()),
            mention=data.get("mention"),
            reason_code=data.get("reason_code") or "")


def _identity_candidates(parts, *, chat_id: int, entity_type: str
                         ) -> tuple[mc.ResolutionCandidate, ...]:
    """Кандидаты неоднозначности, ограниченные тем же chat scope и типом."""
    out: list[mc.ResolutionCandidate] = []
    seen: set[int] = set()
    for candidate in parts or ():
        if not isinstance(candidate, mc.ResolutionCandidate):
            continue
        ref = candidate.ref
        if not _same_chat(ref.chat_id, chat_id):
            continue
        if ref.entity_type != entity_type:
            continue
        if ref.node_id in seen:
            continue
        seen.add(ref.node_id)
        out.append(candidate)
    return tuple(out)


def project_identity(
    *,
    chat_id: Any,
    entity_type: Any,
    resolution: mc.EntityResolution | None = None,
    participant_id: Any = None,
    mention: Any = None,
) -> SemanticIdentity:
    """Typed-оценка результата существующего `entity_resolver.resolve_entity`.

    Ничего не разрешает повторно и не вызывает резолвер: получает готовый
    `EntityResolution` (или его отсутствие) и честно классифицирует.

    * резолв по устойчивой Telegram-идентичности → `participant_identity`,
      `verified`, `canonical` выставлен;
    * резолв по имени/алиасу/casefold для `user` → `name_hint`, `tentative`,
      `canonical is None`, референс только в `hint_ref`;
    * `ambiguous` → `unknown` + `candidates` (≥2), без выбранного canonical;
    * `rejected`/`new` и чужой chat scope → `rejected`/`unknown`, без canonical;
    * известный UID без резолва → `participant_identity`/`verified` (личность
      известна, адрес узла — нет: `canonical is None`).
    """
    chat = _chat_id(chat_id)
    etype = _entity_type(entity_type)
    mention_text = _mention(mention)
    participant = _opt_id(participant_id, "participant_id")

    if etype not in mc.ENTITY_TYPES_ALLOWED:
        return SemanticIdentity(
            chat_id=chat, entity_type=etype or UNKNOWN,
            basis=IDENTITY_BASIS_NONE, status=REJECTED,
            mention=mention_text, reason_code=REASON_INVALID_ENTITY_TYPE)

    if resolution is not None:
        if not isinstance(resolution, mc.EntityResolution):
            raise ValueError("resolution must be EntityResolution or None")
        if not (_same_chat(resolution.scope.chat_id, chat)
                and resolution.scope.entity_type == etype):
            return SemanticIdentity(
                chat_id=chat, entity_type=etype,
                basis=IDENTITY_BASIS_NONE, status=REJECTED,
                mention=mention_text, reason_code=REASON_CROSS_CHAT_SCOPE)

    if resolution is None:
        if participant is not None and etype == "user":
            return SemanticIdentity(
                chat_id=chat, entity_type=etype,
                basis=IDENTITY_BASIS_PARTICIPANT, status=VERIFIED,
                participant_id=participant, mention=mention_text,
                reason_code=REASON_PARTICIPANT_IDENTITY)
        return SemanticIdentity(
            chat_id=chat, entity_type=etype, basis=IDENTITY_BASIS_NONE,
            status=UNKNOWN, mention=mention_text,
            reason_code=REASON_IDENTITY_UNRESOLVED)

    status = resolution.status
    if status is mc.EntityResolutionStatus.AMBIGUOUS:
        candidates = _identity_candidates(
            resolution.candidates, chat_id=chat, entity_type=etype)
        if len(candidates) >= 2:
            return SemanticIdentity(
                chat_id=chat, entity_type=etype,
                basis=IDENTITY_BASIS_NAME_HINT, status=UNKNOWN,
                candidates=candidates, mention=mention_text,
                reason_code=_reason(resolution.reason_code)
                or REASON_NAME_HINT_AMBIGUOUS)
        return SemanticIdentity(
            chat_id=chat, entity_type=etype, basis=IDENTITY_BASIS_NONE,
            status=UNKNOWN, mention=mention_text,
            reason_code=_reason(resolution.reason_code)
            or REASON_IDENTITY_UNRESOLVED)

    if status is mc.EntityResolutionStatus.REJECTED:
        return SemanticIdentity(
            chat_id=chat, entity_type=etype, basis=IDENTITY_BASIS_NONE,
            status=REJECTED, mention=mention_text,
            reason_code=_reason(resolution.reason_code)
            or REASON_IDENTITY_UNRESOLVED)
    if status is mc.EntityResolutionStatus.NEW:
        return SemanticIdentity(
            chat_id=chat, entity_type=etype, basis=IDENTITY_BASIS_NONE,
            status=UNKNOWN, mention=mention_text,
            reason_code=_reason(resolution.reason_code)
            or REASON_IDENTITY_UNRESOLVED)

    ref = resolution.canonical
    if etype == "user":
        if _resolution_is_uid_proven(resolution):
            return SemanticIdentity(
                chat_id=chat, entity_type=etype,
                basis=IDENTITY_BASIS_PARTICIPANT, status=VERIFIED,
                participant_id=participant, canonical=ref,
                mention=mention_text,
                reason_code=_reason(resolution.reason_code)
                or REASON_PARTICIPANT_IDENTITY)
        # Имя/алиас/написание: подсказка, не канонический человек.
        return SemanticIdentity(
            chat_id=chat, entity_type=etype,
            basis=IDENTITY_BASIS_NAME_HINT, status=TENTATIVE,
            hint_ref=ref, mention=mention_text,
            reason_code=_reason(resolution.reason_code)
            or REASON_NAME_HINT_ONLY)
    # topic/event/fact: адрес существующей строки в chat scope (не личность).
    return SemanticIdentity(
        chat_id=chat, entity_type=etype, basis=IDENTITY_BASIS_ADDRESS,
        status=VERIFIED, canonical=ref, mention=mention_text,
        reason_code=_reason(resolution.reason_code) or REASON_NODE_ADDRESS)


# ── Роль значения: speaker ≠ subject ───────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class SemanticRole:
    """Слот значения (`speaker`/`subject`).

    Роль описывает именно свой слот: `subject` никогда не заполняется автором
    сообщения и наоборот. Неизвестная роль остаётся `identity is None` с
    `reason_code`, а не подстановкой соседнего слота.
    """

    role: str
    identity: SemanticIdentity | None = None
    mention: str | None = None
    reason_code: str = ""

    def __post_init__(self) -> None:
        role = str(self.role or "").strip()
        if role not in MEANING_ROLES:
            raise ValueError(
                f"SemanticRole.role invalid: {role!r}; allowed: "
                f"{sorted(MEANING_ROLES)}")
        if self.identity is not None and not isinstance(
                self.identity, SemanticIdentity):
            raise ValueError("SemanticRole.identity must be SemanticIdentity")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "mention", _mention(self.mention))
        object.__setattr__(self, "reason_code", _reason(self.reason_code))

    @property
    def is_known(self) -> bool:
        """Кто/что в этом слоте действительно установлен (не подсказка)."""
        return self.identity is not None and self.identity.is_identity_confirmed

    @property
    def is_hint(self) -> bool:
        return self.identity is not None and self.identity.is_hint_only

    def as_dict(self) -> dict:
        return {
            "role": self.role,
            "identity": self.identity.as_dict() if self.identity else None,
            "mention": self.mention,
            "known": self.is_known,
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticRole":
        identity = data.get("identity")
        return cls(role=data["role"],
                   identity=(SemanticIdentity.from_dict(identity)
                             if identity else None),
                   mention=data.get("mention"),
                   reason_code=data.get("reason_code") or "")


# ── Три независимых времени (+ существующий temporal scope) ─────────────────

@dataclasses.dataclass(frozen=True)
class MeaningTime:
    """Времена значения: событие ≠ утверждение ≠ обнаружение (§3.1).

    Ни одно значение не подставляется вместо другого: `event_time` (T_event —
    когда утверждаемая действительность произошла), `asserted_at` (T_assertion
    — когда утверждение произнесено), `observed_at` (T_observed — когда
    записано в память). Отсутствующее остаётся `None`.
    """

    event_time: int | None = None
    asserted_at: int | None = None
    observed_at: int | None = None
    valid_from: int | None = None
    valid_to: int | None = None

    def __post_init__(self) -> None:
        for name in ("event_time", "asserted_at", "observed_at",
                     "valid_from", "valid_to"):
            object.__setattr__(
                self, name, _opt_ts(getattr(self, name), f"MeaningTime.{name}"))
        if (self.valid_from is not None and self.valid_to is not None
                and self.valid_from > self.valid_to):
            raise ValueError(
                "MeaningTime.valid_from must not be after valid_to")

    @property
    def has_event_time(self) -> bool:
        return self.event_time is not None

    @property
    def has_assertion_time(self) -> bool:
        return self.asserted_at is not None

    def as_dict(self) -> dict:
        return {
            "event_time": self.event_time,
            "asserted_at": self.asserted_at,
            "observed_at": self.observed_at,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MeaningTime":
        return cls(event_time=data.get("event_time"),
                   asserted_at=data.get("asserted_at"),
                   observed_at=data.get("observed_at"),
                   valid_from=data.get("valid_from"),
                   valid_to=data.get("valid_to"))


# ── Семантическое значение целиком ─────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class SemanticMeaning:
    """Read-only типизированное значение памяти (узел или факт).

    `type` — типизированный тип, `identity` — идентичность референта-узла
    (`None` для факта: адрес факта — `fact_id`), `speaker`/`subject` — разные
    слоты, `provenance_class`/`origin_class` — существующие классы владельца
    provenance (не пересчёт), `verification` — **выводимое** свойство.
    """

    chat_id: int
    entity_type: str
    type: TypedEntityType
    time: MeaningTime = dataclasses.field(default_factory=MeaningTime)
    speaker: SemanticRole = dataclasses.field(
        default_factory=lambda: SemanticRole(ROLE_SPEAKER))
    subject: SemanticRole = dataclasses.field(
        default_factory=lambda: SemanticRole(ROLE_SUBJECT))
    identity: SemanticIdentity | None = None
    provenance_class: str | None = None
    origin_class: mc.OriginClass | None = None
    origin: str | None = None
    conflict_status: str = UNKNOWN
    node_id: int | None = None
    fact_id: int | None = None
    source_ref_id: int | None = None
    tg_message_id: int | None = None
    forwarded: bool = False
    degraded: tuple[str, ...] = ()
    reason_code: str = ""

    def __post_init__(self) -> None:
        chat_id = _chat_id(self.chat_id)
        entity_type = _entity_type(self.entity_type)
        if not isinstance(self.type, TypedEntityType):
            raise ValueError("SemanticMeaning.type must be TypedEntityType")
        if self.type.entity_type not in (None, entity_type):
            raise ValueError(
                "SemanticMeaning.type must describe the same entity_type")
        if not isinstance(self.time, MeaningTime):
            raise ValueError("SemanticMeaning.time must be MeaningTime")
        for role in (self.speaker, self.subject):
            if not isinstance(role, SemanticRole):
                raise ValueError(
                    "SemanticMeaning speaker/subject must be SemanticRole")
        if self.speaker.role != ROLE_SPEAKER:
            raise ValueError(
                "SemanticMeaning.speaker must carry role='speaker'")
        if self.subject.role != ROLE_SUBJECT:
            raise ValueError(
                "SemanticMeaning.subject must carry role='subject'")
        identity = self.identity
        if identity is not None and not isinstance(identity, SemanticIdentity):
            raise ValueError("SemanticMeaning.identity must be SemanticIdentity")
        for part in (identity, self.speaker.identity, self.subject.identity):
            if part is None:
                continue
            if not _same_chat(part.chat_id, chat_id):
                raise ValueError(
                    "SemanticMeaning identity must stay in the same chat scope")
        if identity is not None and entity_type and identity.entity_type != entity_type:
            raise ValueError(
                "SemanticMeaning.identity must match the entity_type")
        provenance_class = self.provenance_class
        if provenance_class is not None and provenance_class not in (
                _FACT_PROVENANCE_CLASSES):
            raise ValueError(
                f"provenance_class invalid: {provenance_class!r}")
        origin_class = self.origin_class
        if origin_class is not None:
            if not isinstance(origin_class, mc.OriginClass):
                # существующий владелец отдаёт строку этого же словаря
                try:
                    origin_class = mc.OriginClass(str(origin_class))
                except ValueError:
                    raise ValueError(
                        "origin_class must be memory_contracts.OriginClass")
            object.__setattr__(self, "origin_class", origin_class)
        conflict_status = str(self.conflict_status or UNKNOWN)
        if conflict_status not in provenance.CONFLICT_STATUSES:
            raise ValueError(
                f"conflict_status invalid: {conflict_status!r}")
        degraded = tuple(self.degraded or ())
        for value in degraded:
            if value not in DEGRADED_CODES:
                raise ValueError(f"degraded code invalid: {value!r}")
        if not isinstance(self.forwarded, bool):
            raise ValueError("SemanticMeaning.forwarded must be bool")
        object.__setattr__(self, "chat_id", chat_id)
        object.__setattr__(self, "entity_type", entity_type)
        object.__setattr__(self, "provenance_class", provenance_class)
        object.__setattr__(self, "origin_class", origin_class)
        origin = self.origin
        if origin is not None:
            if not isinstance(origin, str):
                raise ValueError("SemanticMeaning.origin must be str or None")
            origin = origin.strip()[:64] or None
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "conflict_status", conflict_status)
        object.__setattr__(self, "node_id",
                           _opt_id(self.node_id, "SemanticMeaning.node_id"))
        object.__setattr__(self, "fact_id",
                           _opt_id(self.fact_id, "SemanticMeaning.fact_id"))
        object.__setattr__(
            self, "source_ref_id",
            _opt_id(self.source_ref_id, "SemanticMeaning.source_ref_id"))
        object.__setattr__(
            self, "tg_message_id",
            _opt_id(self.tg_message_id, "SemanticMeaning.tg_message_id"))
        object.__setattr__(self, "degraded", degraded)
        object.__setattr__(self, "reason_code", _reason(self.reason_code))

    @property
    def verification(self) -> str:
        """Выводимая достоверность значения (никогда не выставляется вручную).

        Референциальное значение узла (`provenance_class is None`) достоверно
        ровно настолько, насколько типизированы тип и идентичность. Значение
        факта дополнительно требует существующего provenance-контракта:

        * нет атрибуции вовсе (`legacy_unverified`) или co-occurrence → `unknown`;
        * атрибуция без установленного происхождения, дериватив/вывод бота,
          цитата/репост, конфликт → `tentative` (weak hint, не подтверждение);
        * `verified` — только подтверждающее происхождение при типизированном
          типе и доказанной идентичности.
        """
        if self.type.status == REJECTED or (
                self.identity is not None
                and self.identity.status == REJECTED):
            return REJECTED
        if self.type.status == UNKNOWN or (
                self.identity is not None
                and self.identity.status == UNKNOWN):
            return UNKNOWN
        typed_ok = self.type.status == VERIFIED
        identity_ok = (self.identity is None
                       or self.identity.status == VERIFIED)
        if self.provenance_class is None and self.origin_class is None:
            return VERIFIED if (typed_ok and identity_ok) else TENTATIVE
        if self.conflict_status == "conflicting":
            return TENTATIVE
        if self.provenance_class == grp.EDGE_LEGACY_UNVERIFIED:
            return UNKNOWN
        origin = self.origin_class
        if origin is not None and origin in _NON_CONFIRMING_ORIGINS:
            return UNKNOWN
        if self.provenance_class == grp.EDGE_TENTATIVE:
            return TENTATIVE
        if origin is None or origin not in _CONFIRMING_ORIGINS:
            return TENTATIVE
        if typed_ok and identity_ok:
            return VERIFIED
        return TENTATIVE

    @property
    def is_verified(self) -> bool:
        return self.verification == VERIFIED

    def as_dict(self) -> dict:
        return {
            "chat_id": self.chat_id,
            "entity_type": self.entity_type,
            "type": self.type.as_dict(),
            "identity": self.identity.as_dict() if self.identity else None,
            "speaker": self.speaker.as_dict(),
            "subject": self.subject.as_dict(),
            "time": self.time.as_dict(),
            "provenance_class": self.provenance_class,
            "origin_class": (self.origin_class.value
                             if self.origin_class is not None else None),
            "origin": self.origin,
            "conflict_status": self.conflict_status,
            "verification": self.verification,
            "node_id": self.node_id,
            "fact_id": self.fact_id,
            "source_ref_id": self.source_ref_id,
            "tg_message_id": self.tg_message_id,
            "forwarded": self.forwarded,
            "degraded": list(self.degraded),
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticMeaning":
        identity = data.get("identity")
        return cls(
            chat_id=data["chat_id"], entity_type=data["entity_type"],
            type=TypedEntityType.from_dict(data["type"]),
            time=MeaningTime.from_dict(data.get("time") or {}),
            speaker=SemanticRole.from_dict(data["speaker"]),
            subject=SemanticRole.from_dict(data["subject"]),
            identity=(SemanticIdentity.from_dict(identity)
                      if identity else None),
            provenance_class=data.get("provenance_class"),
            origin_class=data.get("origin_class"),
            origin=data.get("origin"),
            conflict_status=data.get("conflict_status", UNKNOWN),
            node_id=data.get("node_id"), fact_id=data.get("fact_id"),
            source_ref_id=data.get("source_ref_id"),
            tg_message_id=data.get("tg_message_id"),
            forwarded=bool(data.get("forwarded", False)),
            degraded=tuple(data.get("degraded") or ()),
            reason_code=data.get("reason_code") or "")


def _degraded_codes(*, typed: TypedEntityType,
                    identity: SemanticIdentity | None,
                    speaker: SemanticRole, subject: SemanticRole,
                    provenance_class: str | None) -> tuple[str, ...]:
    """Честные коды деградации проекции (без текстов и без шума)."""
    codes: list[str] = []
    if typed.status == TENTATIVE:
        codes.append(DEGRADED_TYPE_SIGNALS_INCOMPLETE)
    if identity is not None:
        if identity.status == TENTATIVE:
            codes.append(DEGRADED_IDENTITY_HINT_ONLY)
        elif identity.status == UNKNOWN:
            codes.append(DEGRADED_IDENTITY_UNRESOLVED)
    if not speaker.is_known or not subject.is_known:
        codes.append(DEGRADED_ROLE_UNRESOLVED)
    if (provenance_class is not None
            and provenance_class != grp.EDGE_CONFIDENT):
        codes.append(DEGRADED_PROVENANCE_NOT_CONFIRMED)
    return tuple(dict.fromkeys(codes))


# ── Адаптеры существующих строк (read-only, без SQL) ───────────────────────

def project_node_meaning(
    row: Any,
    *,
    identity_resolution: mc.EntityResolution | None = None,
    participant_id: Any = None,
    speaker_identity: SemanticIdentity | None = None,
    time: MeaningTime | None = None,
) -> SemanticMeaning:
    """Typed-значение строки `nodes` (без записи и без чтения БД).

    Тип берётся из валидного `entity_type` строки; сигналы (`participant
    identity`, `event_time`, statement provenance) — из фактических аргументов,
    а не из `entity_name`. Поэтому одинаковый текст в разных типах даёт разные
    значения, а `user` без UID остаётся подсказкой.
    """
    data = _row_map(row)
    chat = _chat_id(data.get("chat_id"))
    entity_type = _entity_type(data.get("entity_type"))
    node_id = _row_int(data, "id")
    meaning_time = time if isinstance(time, MeaningTime) else MeaningTime()

    identity = project_identity(
        chat_id=chat, entity_type=entity_type,
        resolution=identity_resolution, participant_id=participant_id,
        mention=_row_text(data, "entity_name"))
    if (identity_resolution is None and identity.basis == IDENTITY_BASIS_NONE
            and identity.status == UNKNOWN
            and entity_type in mc.ENTITY_TYPES_ALLOWED
            and entity_type != "user" and node_id is not None):
        # topic/event/fact: адрес существующей строки в chat scope (не личность)
        identity = SemanticIdentity(
            chat_id=chat, entity_type=entity_type,
            basis=IDENTITY_BASIS_ADDRESS, status=VERIFIED,
            canonical=mc.EntityRef(
                chat_id=chat, node_id=node_id, entity_type=entity_type,
                display_name=_row_text(data, "entity_name") or str(node_id)),
            mention=_row_text(data, "entity_name"),
            reason_code=REASON_NODE_ADDRESS)
    has_participant = identity.is_person_confirmed
    has_statement = (
        (speaker_identity is not None
         and speaker_identity.status == VERIFIED)
        or meaning_time.has_assertion_time)
    typed = classify_entity_type(
        entity_type, chat_id=chat, has_participant_identity=has_participant,
        has_statement_provenance=has_statement,
        event_time=meaning_time.event_time)

    speaker = SemanticRole(
        ROLE_SPEAKER, identity=speaker_identity,
        reason_code="" if speaker_identity is not None else REASON_ROLE_UNRESOLVED)
    # Узел сам по себе ничего не утверждает: субъект не подставляется.
    subject = SemanticRole(ROLE_SUBJECT, reason_code=REASON_ROLE_UNRESOLVED)
    return SemanticMeaning(
        chat_id=chat, entity_type=entity_type, type=typed, time=meaning_time,
        speaker=speaker, subject=subject, identity=identity,
        node_id=node_id, origin=_row_text(data, "origin"),
        degraded=_degraded_codes(
            typed=typed, identity=identity, speaker=speaker, subject=subject,
            provenance_class=None),
        reason_code=typed.reason_code)


def project_fact_meaning(
    row: Any,
    *,
    speaker_resolution: mc.EntityResolution | None = None,
    subject_resolution: mc.EntityResolution | None = None,
    conflict_status: str = UNKNOWN,
    source_ref_id: Any = None,
) -> SemanticMeaning:
    """Typed-значение строки `graph_facts` (read-only, существующие владельцы).

    Speaker берётся из `speaker_author_id`, subject — из `subject_ref_id`
    (разные колонки и разные подписи), времена — из `message_timestamp`
    (утверждение) и `created_at` (обнаружение); `event_time` не выдумывается.
    Классы происхождения и достоверности считают `graphrag_provenance`
    `classify_fact_provenance`/`classify_origin_class` — здесь нет их копии.
    """
    data = _row_map(row)
    chat = _chat_id(data.get("chat_id"))
    fact_id = _row_int(data, "id")
    meaning_time = MeaningTime(
        asserted_at=_row_int(data, "message_timestamp"),
        observed_at=_row_int(data, "created_at"),
        valid_from=_row_int(data, "valid_from"),
        valid_to=_row_int(data, "valid_to"))

    speaker_uid = _row_int(data, "speaker_author_id")
    subject_uid = _row_int(data, "subject_ref_id")
    speaker_identity = (
        project_identity(chat_id=chat, entity_type="user",
                         resolution=speaker_resolution,
                         participant_id=speaker_uid)
        if (speaker_uid is not None or speaker_resolution is not None)
        else None)
    subject_identity = (
        project_identity(chat_id=chat, entity_type="user",
                         resolution=subject_resolution,
                         participant_id=subject_uid)
        if (subject_uid is not None or subject_resolution is not None)
        else None)

    speaker = SemanticRole(
        ROLE_SPEAKER, identity=speaker_identity,
        reason_code="" if speaker_identity is not None else REASON_ROLE_UNRESOLVED)
    subject = SemanticRole(
        ROLE_SUBJECT, identity=subject_identity,
        reason_code="" if subject_identity is not None else REASON_ROLE_UNRESOLVED)

    has_statement = (
        (speaker_identity is not None
         and speaker_identity.status == VERIFIED)
        or meaning_time.has_assertion_time)
    typed = classify_entity_type(
        "fact", chat_id=chat, has_statement_provenance=has_statement)

    provenance_class = grp.classify_fact_provenance(data)
    origin_class = grp.classify_origin_class(
        entity_type="graph_fact", source_row=data)
    forwarded = bool(_row_text(data, "forward_from")) or (
        _row_text(data, "perspective") == "quoted")
    return SemanticMeaning(
        chat_id=chat, entity_type="fact", type=typed, time=meaning_time,
        speaker=speaker, subject=subject, identity=None,
        provenance_class=provenance_class, origin_class=origin_class,
        origin=_row_text(data, "origin"),
        conflict_status=conflict_status, fact_id=fact_id,
        source_ref_id=source_ref_id,
        tg_message_id=_row_int(data, "tg_message_id"),
        forwarded=forwarded,
        degraded=_degraded_codes(
            typed=typed, identity=None, speaker=speaker, subject=subject,
            provenance_class=provenance_class),
        reason_code=typed.reason_code)
