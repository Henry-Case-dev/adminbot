"""EPIC-MEMORY-COGNITIVE-02 / MEMORY-01 — логический контракт памяти.

Модуль описывает **логический**, а не параллельный физический контракт над уже
существующими таблицами (`nodes`/`edges`/`graph_facts`/`mca_source_refs`/
`mca_evidence_links`). Здесь нет SQL, доступа к БД, кэшей, второго хранилища и
второго поиска: только типы, закрытые наборы значений и инварианты, которые
нельзя выразить нечестно.

Источник: `plans/features/memory-cognitive-02/contracts.md` (rev3) —
§1 (C-1 идентичность), §2 (C-2 ребро и основания), §3 (C-3 время/модальность),
§4 (C-4 поиск), §7 (C-7 память на стороне ответа), §8 (C-8 атрибуция);
`plans/features/memory-cognitive-02/audit-a0.md` §7 — точный touch-set слайса.

Жёсткие правила модуля (проверяются `tests/test_memory_contracts.py`):

* отсутствующий сигнал → `unknown`, а не `asserted`;
* `RelationView(status='confirmed')` без проверенного независимого основания
  (`supports`/`derived_from` + `verified` + `independent` + разрешимый источник)
  создать невозможно — конструктор бросает `ValueError`;
* `mentions`/`cooccurrence`/`legacy_unknown` никогда не дают независимую
  поддержку и **не понижают** ребро, у которого есть проверенный корень:
  `origin_class` выводится по сильнейшему проверенному корню, слабые основания
  видны отдельно (`has_unsupported_sources`, `legacy_sources_count`);
* `EntityResolution` не умеет сливать сущности: операции «два ref → один» нет,
  `ambiguous` всегда несёт ≥2 варианта с различающим признаком, автовыбор
  канонического при неоднозначности запрещён конструктором;
* времена утверждения (T_assertion), действительности (T_event) и наблюдения
  (T_observed) раздельны и никогда не подставляются «сейчас»;
* исходы поиска (`SearchResponse.status`/`query_state`) — взаимоисключающие
  значения: «пусто» не подменяет «нет прав», «ошибку» и «устаревший курсор»;
* C-8 (§8): адресат либо доказан реальным сигналом, либо `ambiguous`/`unknown`
  без выдуманного получателя; содержание пересылки принадлежит первоисточнику
  (не переславшему); собственный вывод бота не подтверждает внешний факт;
  описание медиа невозможно без `vision_status='processed'`; `STABLE`-вывод
  опыта невозможен без ≥ требуемого числа независимых исходов.

REUSE (§0.2, INV-03): `LINK_TYPES`/`VERIFICATIONS`/`INDEPENDENCES`/
`ASSERTION_KINDS` берутся из `services.provenance`. `PREVIEW_MAX_CHARS`,
`EDGE_WEIGHT_CAP`, `LEGACY_EDGE_WEIGHT_CAP` резолвятся из своих настоящих домов
(`mca_retrieval_context._PREVIEW_MAX_CHARS`, `database._EDGE_WEIGHT_CAP`,
`graphrag_provenance._BARE_EDGE_WEIGHT_CAP`) лениво: импортировать
`services.database` / `services.mca_retrieval_context` на уровне модуля нельзя
(циклы и лишние побочные эффекты при импорте). Дублировать значения запрещено.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from services import provenance

__all__ = [
    # закрытые наборы значений
    "AssertionMode", "OriginClass", "RelationStatus", "EntityResolutionStatus",
    "SearchStatus", "QueryState", "MemoryPurpose", "IntentMode",
    "SearchScopeMode", "RefKind", "MatchCause", "EvidenceStatus",
    # константы
    "LINK_TYPES", "VERIFICATIONS", "INDEPENDENCES", "ASSERTION_KINDS",
    "SUPPORTING_LINK_TYPES", "WEAK_LINK_TYPES", "SUPPORTING_ORIGIN_CLASSES",
    "ENTITY_TYPES_ALLOWED", "ENTITY_CASEFOLD_MAX_ROWS",
    "ENTITY_CASEFOLD_MIN_PREFIX", "SEARCH_LIMIT_MAX", "SEARCH_QUERY_MAX_CHARS",
    "ENTITY_MENTION_MAX_CHARS", "CATEGORIES", "DEGRADED_REASONS",
    "LEGACY_EXPLANATION",
    "preview_max_chars", "edge_weight_cap", "legacy_edge_weight_cap",
    # типы
    "EntityRef", "EntityScope", "ResolutionCandidate", "EntityResolution",
    "RelationSourceView", "RelationView", "IntentHint", "TimeHint",
    "SearchScope", "SearchIntent", "SearchRevision", "SearchFocus",
    "SearchVariant", "SearchAmbiguity", "SearchItem", "SearchResponse",
    "MemoryViewRef", "MemoryView",
    # C-8: атрибуция (MEM-05.1…05.7)
    "AddresseeStatus", "AddresseeBasis", "SpeakerKind", "MediaVisionStatus",
    "ExperienceStability", "AddresseeResolution", "StatementAttribution",
    "MediaMemoryAttribution", "ExperienceVerdict", "MEDIA_MEMORY_REASONS",
    "EXPERIENCE_BASES",
    # функции
    "resolve_assertion_mode",
]

# ── Разделяемые значения из существующих домов (не дублировать) ─────────────

LINK_TYPES = provenance.LINK_TYPES            # derived_from|supports|contradicts|mentions|supersedes
VERIFICATIONS = provenance.VERIFICATIONS      # verified|tentative|rejected|unknown
INDEPENDENCES = provenance.INDEPENDENCES      # independent|self_referential|unknown
ASSERTION_KINDS = provenance.ASSERTION_KINDS  # biographical|…|unknown

# Типы связей, которые вообще могут быть основанием (R-1/§2.3).
SUPPORTING_LINK_TYPES = frozenset({"derived_from", "supports"})
# Слабые основания: не подтверждают и не понижают статус (§2.3, R-11).
WEAK_LINK_TYPES = frozenset({"mentions", "contradicts", "supersedes"})

# Тип узла — ровно существующий CHECK `nodes.entity_type` (§1.1).
ENTITY_TYPES_ALLOWED: tuple[str, ...] = ("user", "topic", "event", "fact")

# §1.2.2: ограниченная генерация casefold-кандидатов (значение фиксируется
# после замера на реальной БД; до замера это параметр, а не «оптимум»).
ENTITY_CASEFOLD_MAX_ROWS = 32
ENTITY_CASEFOLD_MIN_PREFIX = 1

# §4.1: `limit ≤ 20` для UI-поиска; §1.2.7: `q` 1…200 символов.
SEARCH_LIMIT_MAX = 20
SEARCH_QUERY_MAX_CHARS = 200

# §1.2.7: mention длиннее 200 символов → `rejected`, не `new`.
ENTITY_MENTION_MAX_CHARS = 200

# §4.3: человеческие названия категорий результата.
CATEGORIES = frozenset({
    "Человек", "Событие", "Факт", "Убеждение", "Тема", "Связь",
})

# §1.1/§1.4.2: честная деградация идентичности (не «успешный» резолв).
DEGRADED_REASONS = frozenset({
    "identity_not_seeded", "casefold_prefix_overflow",
    "redirect_chain_flattened",
})

# §2.3/R-7: текстовая формулировка для ребра без установленного происхождения.
LEGACY_EXPLANATION = "Происхождение не установлено"

# §7.2/R17: человеческий текст не содержит внутренних id/метрик.
_INTERNAL_TOKEN_RE = re.compile(
    r"(?:\bnode_id\b|\bedge_id\b|\bsource_ref_id\b|\bchat_id\b|\bcosine\b"
    r"|\bent:|\bfact:|\bedge:|\bcomm:)",
    re.IGNORECASE,
)

# ── Ленивые константы из настоящих домов ───────────────────────────────────
# Ключ → (модуль, имя). Резолв по требованию: модуль-контракт остаётся
# импортируемым без БД и без тяжёлых сервисов.
_LAZY_CONSTANTS: dict[str, tuple[str, str]] = {
    "PREVIEW_MAX_CHARS": ("services.mca_retrieval_context", "_PREVIEW_MAX_CHARS"),
    "EDGE_WEIGHT_CAP": ("services.database", "_EDGE_WEIGHT_CAP"),
    "LEGACY_EDGE_WEIGHT_CAP": (
        "services.graphrag_provenance", "_BARE_EDGE_WEIGHT_CAP"),
}


def _resolve_lazy(name: str) -> Any:
    module_name, attr = _LAZY_CONSTANTS[name]
    module = __import__(module_name, fromlist=[attr])
    return getattr(module, attr)


def preview_max_chars() -> int:
    """Граница превью/сниппета — `mca_retrieval_context._PREVIEW_MAX_CHARS`."""
    return int(_resolve_lazy("PREVIEW_MAX_CHARS"))


def edge_weight_cap() -> int:
    """Верхний предел `edges.weight` — `database._EDGE_WEIGHT_CAP` (§2.6 R-2)."""
    return int(_resolve_lazy("EDGE_WEIGHT_CAP"))


def legacy_edge_weight_cap() -> float:
    """Предел веса legacy-ребра — `graphrag_provenance._BARE_EDGE_WEIGHT_CAP`."""
    return float(_resolve_lazy("LEGACY_EDGE_WEIGHT_CAP"))


def __getattr__(name: str) -> Any:            # PEP 562
    if name in _LAZY_CONSTANTS:
        return _resolve_lazy(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(list(globals()) + list(_LAZY_CONSTANTS)))


# ── Закрытые наборы значений (Enum) ────────────────────────────────────────

class _StrEnum(str, Enum):
    """Строковый enum: значение — стабильная строка контракта."""

    def __str__(self) -> str:                 # pragma: no cover - удобство
        return str(self.value)


class AssertionMode(_StrEnum):
    """Модальность утверждения (§2.1, §3.3.1).

    `UNKNOWN` — значение по умолчанию: отсутствующий сигнал **никогда** не
    превращается в `ASSERTED`.
    """

    ASSERTED = "asserted"
    QUOTED = "quoted"
    REPORTED = "reported"
    INFERRED = "inferred"
    DENIED = "denied"
    HYPOTHETICAL = "hypothetical"
    JOKING = "joking"
    UNKNOWN = "unknown"


class OriginClass(_StrEnum):
    """Класс происхождения основания (§2.2); порядок = сила доказательства."""

    EXPLICIT_DIRECT = "explicit_direct"
    REPORTED_THIRD_PARTY = "reported_third_party"
    QUOTE_FORWARD = "quote_forward"
    DERIVED_WITH_LINEAGE = "derived_with_lineage"
    COOCCURRENCE = "cooccurrence"
    LEGACY_UNKNOWN = "legacy_unknown"


# Только эти классы могут быть корнем подтверждения (§2.3).
SUPPORTING_ORIGIN_CLASSES = frozenset({
    OriginClass.EXPLICIT_DIRECT, OriginClass.REPORTED_THIRD_PARTY,
    OriginClass.QUOTE_FORWARD, OriginClass.DERIVED_WITH_LINEAGE,
})

_ORIGIN_STRENGTH: tuple[OriginClass, ...] = (
    OriginClass.EXPLICIT_DIRECT, OriginClass.REPORTED_THIRD_PARTY,
    OriginClass.QUOTE_FORWARD, OriginClass.DERIVED_WITH_LINEAGE,
    OriginClass.COOCCURRENCE, OriginClass.LEGACY_UNKNOWN,
)


class RelationStatus(_StrEnum):
    """Статус ребра (§2.1). `confirmed` требует проверенного корня (R-1)."""

    CONFIRMED = "confirmed"
    TENTATIVE = "tentative"
    UNVERIFIED = "unverified"
    CONTRADICTED = "contradicted"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class EntityResolutionStatus(_StrEnum):
    """Исход `resolve_entity` (§1.2). Слияния здесь нет и быть не может."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NEW = "new"
    REJECTED = "rejected"


class SearchStatus(_StrEnum):
    """Технический исход ручки поиска (§4.3/§4.9)."""

    OK = "ok"
    AMBIGUOUS = "ambiguous"
    EMPTY = "empty"
    LEGACY_ONLY = "legacy_only"
    PARTIAL = "partial"
    FORBIDDEN = "forbidden"
    ERROR = "error"
    CURSOR_STALE = "cursor_stale"


class QueryState(_StrEnum):
    """Пользовательское состояние поиска (§4.3, §10)."""

    LOCAL_MATCHES = "local_matches"
    SERVER_SEARCHING = "server_searching"
    CANDIDATES = "candidates"
    NO_MATCHES = "no_matches"
    WEAK_LEGACY_ONLY = "weak_legacy_only"
    PARTIAL = "partial"
    ERROR = "error"
    NO_RIGHTS = "no_rights"


class MemoryPurpose(_StrEnum):
    """Назначение выборки памяти (§4.4); `ui_search` запрещает LLM/rerank."""

    REPLY = "reply"
    INITIATIVE = "initiative"
    FACTCHECK_CONTEXT = "factcheck_context"
    UI_SEARCH = "ui_search"
    DOSSIER = "dossier"


class IntentMode(_StrEnum):
    """Три режима retrieval для ответа (§7.1, MEM-06.6)."""

    SPECIFIC = "specific"
    EPISODIC = "episodic"
    THEMATIC = "thematic"


class SearchScopeMode(_StrEnum):
    """Режим области поиска (§4.2): один чат либо разрешённый набор чатов."""

    CHAT = "chat"
    SCOPE_ALL = "scope_all"


class RefKind(_StrEnum):
    """Тип результата поиска (§4.3)."""

    ENTITY = "entity"
    FACT = "fact"
    EPISODE = "episode"
    COMMUNITY = "community"
    RELATION = "relation"


class MatchCause(_StrEnum):
    """Причина попадания в выдачу (§4.3)."""

    EXACT_NAME = "exact_name"
    ALIAS = "alias"
    CASEFOLD = "casefold"
    FTS = "fts"
    SEMANTIC = "semantic"
    TEMPORAL = "temporal"
    RELATION_PATH = "relation_path"
    COMMUNITY = "community"


class EvidenceStatus(_StrEnum):
    """Доказательный статус элемента выдачи / ребра (§4.3, §10)."""

    CONFIRMED = "confirmed"
    TENTATIVE = "tentative"
    LEGACY = "legacy"
    CONTRADICTED = "contradicted"
    UNKNOWN = "unknown"


# ── C-8 §8: закрытые наборы атрибуции (MEM-05.1…05.7) ──────────────────────
# Объявлены до DTO, потому что `RelationSourceView` (§2.1) несёт адресата
# отдельным слотом и использует их как значения по умолчанию.

class AddresseeStatus(_StrEnum):
    """Исход определения адресата (§8.2, MEM-05.2).

    `RESOLVED` — адресат доказан одним из документированных сигналов;
    `AMBIGUOUS` — подходят ≥2 адресата, выбор за человека не делается;
    `UNKNOWN` — сигнала нет: в бессвязном чате новый адресат не выдумывается.
    """

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"


class AddresseeBasis(_StrEnum):
    """Сигнал, давший адресата. Порядок значений — приоритет §8.2.

    Точный `reply_to_id` → `thread_chain` target → достоверный alias/uid в
    chat scope (C-1) → ближайший семантический контекст.
    """

    REPLY_TARGET = "reply_target"
    THREAD_TARGET = "thread_target"
    CHAT_IDENTITY = "chat_identity"
    SEMANTIC_CONTEXT = "semantic_context"
    NONE = "none"


class SpeakerKind(_StrEnum):
    """Кто говорит: участник, сам бот или неизвестно (§8.4, MEM-05.4)."""

    PARTICIPANT = "participant"
    BOT = "bot"
    UNKNOWN = "unknown"


class MediaVisionStatus(_StrEnum):
    """Честный статус выжимки медиа (§8.5, MEM-05.5).

    `PROCESSED` — понимание ФАКТИЧЕСКИ выполнено; `NOT_PROCESSED` — не
    выполнялось (в т.ч. ещё идёт); `UNAVAILABLE` — выполнить не удалось.
    Последние два никогда не выдаются за понимание содержимого.
    """

    PROCESSED = "processed"
    NOT_PROCESSED = "not_processed"
    UNAVAILABLE = "unavailable"


class ExperienceStability(_StrEnum):
    """Вывод опыта: экспериментальный или стабильное правило (§8.6)."""

    EXPERIMENTAL = "experimental"
    STABLE = "stable"


#: Закрытый набор причин медиа-памяти (R17: только коды, без текста).
MEDIA_MEMORY_REASONS = frozenset({
    "analysis_ready", "analysis_no_text", "analysis_missing",
    "analysis_pending", "analysis_failed", "analysis_unreadable",
    "analysis_unsupported", "vision_unavailable", "transcription_not_recorded",
    "media_absent", "unknown",
})

#: Закрытый набор оснований стабильности вывода опыта (§8.6).
EXPERIENCE_BASES = frozenset({
    "explicit_instruction", "verified_technical_fix", "independent_outcomes",
})


_INTENT_KINDS = frozenset({
    "person", "fact", "event", "belief", "relation", "topic", "time", "unknown",
})
_SOURCE_KINDS = frozenset({"message", "graph_fact", "episode", "bot_output"})
_SCOPE_MODES = frozenset({"chat", "scope_all"})
_CANONICAL_PREFIX = {
    RefKind.ENTITY: "ent",
    RefKind.FACT: "fact",
    RefKind.EPISODE: "episode",
    RefKind.COMMUNITY: "comm",
    RefKind.RELATION: "edge",
}
_CANONICAL_RE = re.compile(r"^(ent|fact|episode|edge|comm):[^\s:]+(?::[^\s:]+)*$")

# Исход ↔ пользовательское состояние: взаимоисключающая матрица (§4.3/§4.9).
_OUTCOME_MATRIX: dict[SearchStatus, frozenset[QueryState]] = {
    SearchStatus.OK: frozenset({
        QueryState.LOCAL_MATCHES, QueryState.SERVER_SEARCHING,
        QueryState.CANDIDATES,
    }),
    SearchStatus.AMBIGUOUS: frozenset({QueryState.CANDIDATES}),
    SearchStatus.EMPTY: frozenset({QueryState.NO_MATCHES}),
    SearchStatus.LEGACY_ONLY: frozenset({QueryState.WEAK_LEGACY_ONLY}),
    SearchStatus.PARTIAL: frozenset({QueryState.PARTIAL}),
    SearchStatus.FORBIDDEN: frozenset({QueryState.NO_RIGHTS}),
    SearchStatus.ERROR: frozenset({QueryState.ERROR}),
    SearchStatus.CURSOR_STALE: frozenset({
        QueryState.LOCAL_MATCHES, QueryState.CANDIDATES, QueryState.PARTIAL,
    }),
}
_STALE_CURSOR_REASON = "cursor_revision_mismatch"


# ── Мелкие валидаторы ──────────────────────────────────────────────────────

def _enum(cls: type[Enum], value: Any, field_name: str) -> Any:
    if isinstance(value, cls):
        return value
    try:
        return cls(value)
    except ValueError:
        raise ValueError(
            f"{field_name} invalid: {value!r}; allowed: "
            f"{[m.value for m in cls]}") from None


def _int(value: Any, field_name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be int, got {value!r}")
    if value < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}, got {value!r}")
    return value


def _opt_ts(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    return _int(value, field_name, minimum=1)


def _chat_id(value: Any, field_name: str) -> int:
    """Telegram `chat_id` — знаковое число (группы отрицательные), не ноль."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be int, got {value!r}")
    if value == 0:
        raise ValueError(f"{field_name} must be non-zero")
    return value


def _text(value: Any, field_name: str, *, maximum: int | None = None,
          allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be str, got {value!r}")
    if maximum is not None and len(value) > maximum:
        raise ValueError(
            f"{field_name} longer than {maximum}: {len(value)}")
    text = value.strip()
    if not text and not allow_empty:
        raise ValueError(f"{field_name} must be non-empty")
    return text


def _human_text(value: Any, field_name: str, *, maximum: int | None = None) -> str:
    """Человеческий текст: без внутренних id/метрик (§7.2, S-7, R17)."""
    text = _text(value, field_name, maximum=maximum)
    if _INTERNAL_TOKEN_RE.search(text):
        raise ValueError(
            f"{field_name} must not contain internal ids/metrics: {text!r}")
    return text


def _tuple_of(value: Any, field_name: str) -> tuple:
    if isinstance(value, tuple):
        return value
    if isinstance(value, (list, set, frozenset)):
        return tuple(value)
    raise ValueError(f"{field_name} must be a tuple/list, got {value!r}")


def _normalized(instance: Any, name: str, value: Any) -> Any:
    """Нормализует поле frozen-датакласса, сохраняя неизменяемость."""
    object.__setattr__(instance, name, value)
    return value


# ── C-1: сущность и разрешение идентичности ────────────────────────────────

@dataclass(frozen=True)
class EntityRef:
    """Канонический объект памяти (contracts §1.1).

    Идентичность чат-квалифицирована (`chat_id` обязателен, ID-2). `node_id` —
    стабильный legacy-совместимый адрес `nodes.id`; `legacy_ids` — узлы,
    сведённые в этот канонический (аддитивно, без переписывания истории, ID-3).
    `display_name` — текущее видимое имя, не переименовывающее историю.
    """

    chat_id: int
    node_id: int
    entity_type: str
    display_name: str
    legacy_ids: tuple[int, ...] = ()
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _chat_id(self.chat_id, "EntityRef.chat_id")
        _int(self.node_id, "EntityRef.node_id", minimum=1)
        if self.entity_type not in ENTITY_TYPES_ALLOWED:
            raise ValueError(
                f"EntityRef.entity_type invalid: {self.entity_type!r}; "
                f"allowed: {ENTITY_TYPES_ALLOWED}")
        _text(self.display_name, "EntityRef.display_name",
              maximum=ENTITY_MENTION_MAX_CHARS)
        legacy = tuple(_int(v, "EntityRef.legacy_ids[]", minimum=1)
                       for v in _tuple_of(self.legacy_ids, "EntityRef.legacy_ids"))
        if len(set(legacy)) != len(legacy):
            raise ValueError("EntityRef.legacy_ids contains duplicates")
        if self.node_id in legacy:
            raise ValueError(
                "EntityRef.legacy_ids must not contain canonical node_id")
        aliases = tuple(
            _text(a, "EntityRef.aliases[]", maximum=ENTITY_MENTION_MAX_CHARS)
            for a in _tuple_of(self.aliases, "EntityRef.aliases"))
        _normalized(self, "legacy_ids", legacy)
        _normalized(self, "aliases", aliases)

    def as_dict(self) -> dict:
        return {
            "chat_id": self.chat_id, "node_id": self.node_id,
            "entity_type": self.entity_type,
            "display_name": self.display_name,
            "legacy_ids": list(self.legacy_ids),
            "aliases": list(self.aliases),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EntityRef":
        return cls(
            chat_id=data["chat_id"], node_id=data["node_id"],
            entity_type=data["entity_type"],
            display_name=data["display_name"],
            legacy_ids=tuple(data.get("legacy_ids") or ()),
            aliases=tuple(data.get("aliases") or ()),
        )


@dataclass(frozen=True)
class EntityScope:
    """Область разрешения идентичности (§1.1): чат + тип сущности."""

    chat_id: int
    entity_type: str

    def __post_init__(self) -> None:
        _chat_id(self.chat_id, "EntityScope.chat_id")
        if self.entity_type not in ENTITY_TYPES_ALLOWED:
            raise ValueError(
                f"EntityScope.entity_type invalid: {self.entity_type!r}")

    def as_dict(self) -> dict:
        return {"chat_id": self.chat_id, "entity_type": self.entity_type}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EntityScope":
        return cls(chat_id=data["chat_id"], entity_type=data["entity_type"])


@dataclass(frozen=True)
class ResolutionCandidate:
    """Вариант при неоднозначности: ref + причина + **различающий признак**.

    `discriminator` обязателен (ID-8): неоднозначность — данные, а не выбор.
    """

    ref: EntityRef
    reason: str
    discriminator: str

    def __post_init__(self) -> None:
        if not isinstance(self.ref, EntityRef):
            raise ValueError("ResolutionCandidate.ref must be EntityRef")
        _text(self.reason, "ResolutionCandidate.reason")
        _text(self.discriminator, "ResolutionCandidate.discriminator")

    def as_dict(self) -> dict:
        return {"ref": self.ref.as_dict(), "reason": self.reason,
                "discriminator": self.discriminator}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ResolutionCandidate":
        return cls(ref=EntityRef.from_dict(data["ref"]),
                   reason=data["reason"], discriminator=data["discriminator"])


@dataclass(frozen=True)
class EntityResolution:
    """Результат `resolve_entity` (§1.1/§1.2) — без операции слияния.

    `normalized_mention` — диагностика, **не** ключ идентичности (ID-4).
    Неоднозначность не конвертируется в `resolved`: при `ambiguous` канонический
    объект не задаётся, а вариантов обязано быть ≥2 (ID-8). Слияние сущностей —
    отдельная явная операция (ID-3); этого типа она не выражает.
    """

    status: EntityResolutionStatus
    scope: EntityScope
    normalized_mention: str
    canonical: EntityRef | None = None
    candidates: tuple[ResolutionCandidate, ...] = ()
    reason_code: str = ""
    degraded: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        status = _enum(EntityResolutionStatus, self.status,
                       "EntityResolution.status")
        if not isinstance(self.scope, EntityScope):
            raise ValueError("EntityResolution.scope must be EntityScope")
        _text(self.normalized_mention, "EntityResolution.normalized_mention",
              maximum=ENTITY_MENTION_MAX_CHARS, allow_empty=True)
        candidates = _tuple_of(self.candidates, "EntityResolution.candidates")
        for candidate in candidates:
            if not isinstance(candidate, ResolutionCandidate):
                raise ValueError(
                    "EntityResolution.candidates[] must be ResolutionCandidate")
        degraded = tuple(
            _text(v, "EntityResolution.degraded[]", maximum=64)
            for v in _tuple_of(self.degraded, "EntityResolution.degraded"))
        for value in degraded:
            if value not in DEGRADED_REASONS:
                raise ValueError(
                    f"EntityResolution.degraded invalid: {value!r}; allowed: "
                    f"{sorted(DEGRADED_REASONS)}")
        reason_code = str(self.reason_code or "").strip()

        if status is EntityResolutionStatus.RESOLVED:
            if not isinstance(self.canonical, EntityRef):
                raise ValueError(
                    "resolved resolution requires canonical EntityRef")
            if candidates:
                raise ValueError(
                    "resolved resolution must not carry candidates")
            if self.canonical.chat_id != self.scope.chat_id:
                raise ValueError(
                    "resolved canonical must belong to the same chat (ID-2)")
            if self.canonical.entity_type != self.scope.entity_type:
                raise ValueError(
                    "resolved canonical must match scope.entity_type")
        elif status is EntityResolutionStatus.AMBIGUOUS:
            if self.canonical is not None:
                raise ValueError(
                    "ambiguous resolution must not pick a canonical entity "
                    "(ID-8: no auto-selection)")
            if len(candidates) < 2:
                raise ValueError(
                    "ambiguous resolution requires >= 2 candidates (ID-8)")
        elif status is EntityResolutionStatus.NEW:
            if self.canonical is not None or candidates:
                raise ValueError(
                    "new resolution must not carry canonical/candidates")
        else:                                       # REJECTED
            if self.canonical is not None:
                raise ValueError(
                    "rejected resolution must not carry canonical")
            if not reason_code:
                raise ValueError("rejected resolution requires reason_code")

        _normalized(self, "status", status)
        _normalized(self, "candidates", candidates)
        _normalized(self, "degraded", degraded)
        _normalized(self, "reason_code", reason_code)

    @property
    def is_confident(self) -> bool:
        """Только `resolved` без деградации считается уверенным исходом."""
        return (self.status is EntityResolutionStatus.RESOLVED
                and not self.degraded)

    def as_dict(self) -> dict:
        return {
            "status": self.status.value,
            "scope": self.scope.as_dict(),
            "normalized_mention": self.normalized_mention,
            "canonical": self.canonical.as_dict() if self.canonical else None,
            "candidates": [c.as_dict() for c in self.candidates],
            "reason_code": self.reason_code,
            "degraded": list(self.degraded),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EntityResolution":
        canonical = data.get("canonical")
        return cls(
            status=data["status"],
            scope=EntityScope.from_dict(data["scope"]),
            normalized_mention=data.get("normalized_mention", ""),
            canonical=EntityRef.from_dict(canonical) if canonical else None,
            candidates=tuple(ResolutionCandidate.from_dict(c)
                             for c in data.get("candidates") or ()),
            reason_code=data.get("reason_code") or "",
            degraded=tuple(data.get("degraded") or ()),
        )


# ── C-2: ребро, основание и честный подсчёт поддержки ─────────────────────

@dataclass(frozen=True)
class RelationSourceView:
    """Одно основание ребра (§2.1 `sources[]`, §2.3).

    `speaker`/`subject` раздельны (INV-07). Три времени раздельны (§3.1):
    `asserted_ts` (T_assertion — когда утверждение произнесено),
    `event_ts` (T_event — время утверждаемой действительности),
    `observed_ts` (T_observed — когда записано в память). Ни одно не
    подставляется по умолчанию.

    `counts_as_independent` **выводится** из `link_type`/`verification`/
    `independence`/`origin_class`: `mentions` не подтверждает никогда (R-11),
    `cooccurrence`/`legacy_unknown` не могут быть проверенным корнем (§2.3).
    """

    link_type: str
    origin_class: OriginClass
    verification: str
    independence: str
    established_at: int
    method: str = "unknown"
    kind: str = "message"
    assertion_mode: AssertionMode = AssertionMode.UNKNOWN
    source_ref_id: int | None = None
    fact_id: int | None = None
    speaker: str | None = None
    subject: str | None = None
    asserted_ts: int | None = None
    event_ts: int | None = None
    observed_ts: int | None = None
    # C-8 (§8.2/§8.4): роли пересылки/адресата отдельными слотами.
    sender: str | None = None
    addressee: str | None = None
    addressee_status: AddresseeStatus = AddresseeStatus.UNKNOWN
    addressee_basis: AddresseeBasis = AddresseeBasis.NONE
    addressee_candidates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.link_type not in LINK_TYPES:
            raise ValueError(
                f"RelationSourceView.link_type invalid: {self.link_type!r}; "
                f"allowed: {sorted(LINK_TYPES)}")
        origin = _enum(OriginClass, self.origin_class,
                       "RelationSourceView.origin_class")
        if self.verification not in VERIFICATIONS:
            raise ValueError(
                f"RelationSourceView.verification invalid: "
                f"{self.verification!r}")
        if self.independence not in INDEPENDENCES:
            raise ValueError(
                f"RelationSourceView.independence invalid: {self.independence!r}")
        if self.method not in provenance.METHODS:
            raise ValueError(
                f"RelationSourceView.method invalid: {self.method!r}")
        if self.kind not in _SOURCE_KINDS:
            raise ValueError(
                f"RelationSourceView.kind invalid: {self.kind!r}; "
                f"allowed: {sorted(_SOURCE_KINDS)}")
        mode = _enum(AssertionMode, self.assertion_mode,
                     "RelationSourceView.assertion_mode")
        _int(self.established_at, "RelationSourceView.established_at", minimum=1)
        for name in ("source_ref_id", "fact_id"):
            value = getattr(self, name)
            if value is not None:
                _int(value, f"RelationSourceView.{name}", minimum=1)
        for name in ("speaker", "subject", "sender"):
            value = getattr(self, name)
            if value is not None:
                _text(value, f"RelationSourceView.{name}",
                      maximum=ENTITY_MENTION_MAX_CHARS)
        _opt_ts(self.asserted_ts, "RelationSourceView.asserted_ts")
        _opt_ts(self.event_ts, "RelationSourceView.event_ts")
        _opt_ts(self.observed_ts, "RelationSourceView.observed_ts")
        addressee = AddresseeResolution(
            status=self.addressee_status, addressee=self.addressee,
            basis=self.addressee_basis, candidates=self.addressee_candidates)

        supporting = (
            self.link_type in SUPPORTING_LINK_TYPES
            and self.verification == "verified"
            and self.independence == "independent")
        if supporting:
            if origin not in SUPPORTING_ORIGIN_CLASSES:
                raise ValueError(
                    "verified independent support requires a supporting "
                    f"origin class, got {origin.value!r} (§2.3)")
            if self.source_ref_id is None and self.fact_id is None:
                raise ValueError(
                    "verified independent support requires a resolvable source "
                    "(source_ref_id/fact_id) — R-1")
        if origin is OriginClass.COOCCURRENCE and self.link_type != "mentions":
            raise ValueError(
                "cooccurrence origin must use link_type='mentions' (§2.3)")
        _normalized(self, "origin_class", origin)
        _normalized(self, "assertion_mode", mode)
        _normalized(self, "addressee", addressee.addressee)
        _normalized(self, "addressee_status", addressee.status)
        _normalized(self, "addressee_basis", addressee.basis)
        _normalized(self, "addressee_candidates", addressee.candidates)

    @property
    def counts_as_independent(self) -> bool:
        """Независимое подтверждение: только `supports`/`derived_from`."""
        return (
            self.link_type in SUPPORTING_LINK_TYPES
            and self.verification == "verified"
            and self.independence == "independent"
        )

    @property
    def root_key(self) -> tuple:
        """Идентичность корня: один источник дважды = один корень (R-4)."""
        if self.source_ref_id is not None:
            return ("ref", self.source_ref_id)
        if self.fact_id is not None:
            return ("fact", self.fact_id)
        return ("anonymous", id(self))

    def as_dict(self) -> dict:
        return {
            "source_ref_id": self.source_ref_id,
            "fact_id": self.fact_id,
            "kind": self.kind,
            "origin_class": self.origin_class.value,
            "assertion_mode": self.assertion_mode.value,
            "link_type": self.link_type,
            "counts_as_independent": self.counts_as_independent,
            "speaker": self.speaker,
            "subject": self.subject,
            "asserted_ts": self.asserted_ts,
            "event_ts": self.event_ts,
            "observed_ts": self.observed_ts,
            "verification": self.verification,
            "independence": self.independence,
            "method": self.method,
            "established_at": self.established_at,
            "sender": self.sender,
            "addressee": self.addressee,
            "addressee_status": self.addressee_status.value,
            "addressee_basis": self.addressee_basis.value,
            "addressee_candidates": list(self.addressee_candidates),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RelationSourceView":
        return cls(
            link_type=data["link_type"],
            origin_class=data["origin_class"],
            verification=data["verification"],
            independence=data["independence"],
            established_at=data["established_at"],
            method=data.get("method", "unknown"),
            kind=data.get("kind", "message"),
            assertion_mode=data.get("assertion_mode", AssertionMode.UNKNOWN),
            source_ref_id=data.get("source_ref_id"),
            fact_id=data.get("fact_id"),
            speaker=data.get("speaker"),
            subject=data.get("subject"),
            asserted_ts=data.get("asserted_ts"),
            event_ts=data.get("event_ts"),
            observed_ts=data.get("observed_ts"),
            sender=data.get("sender"),
            addressee=data.get("addressee"),
            addressee_status=data.get("addressee_status",
                                       AddresseeStatus.UNKNOWN),
            addressee_basis=data.get("addressee_basis", AddresseeBasis.NONE),
            addressee_candidates=tuple(data.get("addressee_candidates") or ()),
        )


@dataclass(frozen=True)
class RelationView:
    """Логическое ребро (§2.1) — всё выводится, ничего не дублируется в БД.

    `origin_class`, `independent_support`, `legacy_sources_count` и
    `has_unsupported_sources` **выводятся** из `sources`:

    * `origin_class` — класс самого сильного проверенного корня, а не самого
      слабого источника (§2.3; правило «weakest» отменено);
    * `mentions`/`cooccurrence`/`legacy_unknown` не дают независимой поддержки
      и не понижают статус ребра с проверенным корнем — они видны отдельно;
    * `frequency` = `edges.weight` — частота, **не** истина (R-2).
    """

    edge_id: int
    chat_id: int
    source_entity_id: int
    target_entity_id: int
    relation_type: str
    relation_label: str
    status: RelationStatus
    sources: tuple[RelationSourceView, ...] = ()
    legacy_ids: tuple[int, ...] = ()
    frequency: int = 1
    explanation: str = LEGACY_EXPLANATION
    valid_from: int | None = None
    valid_to: int | None = None
    last_confirmed: int | None = None
    confidence_basis: str | None = None
    graph_revision: str = ""
    edge_updated_at: int | None = None
    direction: str = "directed"

    def __post_init__(self) -> None:
        for name in ("edge_id", "source_entity_id", "target_entity_id"):
            _int(getattr(self, name), f"RelationView.{name}", minimum=1)
        _chat_id(self.chat_id, "RelationView.chat_id")
        _text(self.relation_type, "RelationView.relation_type", maximum=64)
        _human_text(self.relation_label, "RelationView.relation_label",
                    maximum=120)
        status = _enum(RelationStatus, self.status, "RelationView.status")
        sources = _tuple_of(self.sources, "RelationView.sources")
        for source in sources:
            if not isinstance(source, RelationSourceView):
                raise ValueError(
                    "RelationView.sources[] must be RelationSourceView")
        legacy_ids = tuple(
            _int(v, "RelationView.legacy_ids[]", minimum=1)
            for v in _tuple_of(self.legacy_ids, "RelationView.legacy_ids"))
        if len(set(legacy_ids)) != len(legacy_ids):
            raise ValueError("RelationView.legacy_ids contains duplicates")
        if self.edge_id in legacy_ids:
            raise ValueError(
                "RelationView.legacy_ids must not contain aggregate edge_id")
        _int(self.frequency, "RelationView.frequency", minimum=0)
        _human_text(self.explanation, "RelationView.explanation",
                    maximum=400)
        _opt_ts(self.valid_from, "RelationView.valid_from")
        _opt_ts(self.valid_to, "RelationView.valid_to")
        _opt_ts(self.last_confirmed, "RelationView.last_confirmed")
        if (self.valid_from is not None and self.valid_to is not None
                and self.valid_from > self.valid_to):
            raise ValueError(
                "RelationView.valid_from must not be after valid_to")
        if self.confidence_basis is not None:
            _text(self.confidence_basis, "RelationView.confidence_basis",
                  maximum=200)
        if self.direction != "directed":
            raise ValueError(
                "RelationView.direction is always 'directed' (edges directed)")
        if self.graph_revision:
            _text(self.graph_revision, "RelationView.graph_revision",
                  maximum=128)
        _opt_ts(self.edge_updated_at, "RelationView.edge_updated_at")

        _normalized(self, "status", status)
        _normalized(self, "sources", sources)
        _normalized(self, "legacy_ids", legacy_ids)

        if status is RelationStatus.CONFIRMED:
            if self.independent_support < 1:
                raise ValueError(
                    "confirmed relation requires >= 1 verified independent "
                    "supports/derived_from source (R-1)")
            if self.explanation == LEGACY_EXPLANATION:
                raise ValueError(
                    "confirmed relation requires an explicit human explanation")
        if (status is RelationStatus.CONFIRMED
                and self.origin_class not in SUPPORTING_ORIGIN_CLASSES):
            raise ValueError(
                "confirmed relation cannot be based on weak origin only")

    # ── выводимые значения (невозможно выставить вручную) ──────────────────
    @property
    def independent_support(self) -> int:
        """Число независимых корней среди проверенных подтверждений (§2.4.2)."""
        roots = {s.root_key for s in self.sources if s.counts_as_independent}
        return len(roots)

    @property
    def legacy_sources_count(self) -> int:
        """Слабые/legacy основания отдельно (§2.3): не понижают статус."""
        return sum(
            1 for s in self.sources
            if s.origin_class is OriginClass.LEGACY_UNKNOWN)

    @property
    def has_unsupported_sources(self) -> bool:
        """Есть основания без подтверждения (риск, а не понижение статуса)."""
        if self.independent_support == 0:
            return True
        return any(
            s.origin_class is OriginClass.LEGACY_UNKNOWN
            or s.link_type == "mentions"
            for s in self.sources)

    @property
    def origin_class(self) -> OriginClass:
        """Класс самого сильного проверенного корня (никогда не weakest)."""
        confirmed = {s.origin_class for s in self.sources
                     if s.counts_as_independent}
        pool = confirmed or {s.origin_class for s in self.sources}
        for candidate in _ORIGIN_STRENGTH:
            if candidate in pool:
                return candidate
        return OriginClass.LEGACY_UNKNOWN

    @property
    def verification_summary(self) -> dict:
        """Сводка для карточки: числа, без текста переписки."""
        return {
            "independent_support": self.independent_support,
            "legacy_sources_count": self.legacy_sources_count,
            "has_unsupported_sources": self.has_unsupported_sources,
            "sources_total": len(self.sources),
        }

    @classmethod
    def legacy(cls, *, edge_id: int, chat_id: int, source_entity_id: int,
               target_entity_id: int, relation_type: str,
               relation_label: str, frequency: int = 1,
               valid_from: int | None = None,
               valid_to: int | None = None,
               edge_updated_at: int | None = None) -> "RelationView":
        """Честное legacy-ребро: происхождение не установлено (R-7)."""
        return cls(
            edge_id=edge_id, chat_id=chat_id,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            relation_type=relation_type, relation_label=relation_label,
            status=RelationStatus.UNVERIFIED, sources=(), frequency=frequency,
            explanation=LEGACY_EXPLANATION, valid_from=valid_from,
            valid_to=valid_to, edge_updated_at=edge_updated_at,
        )

    def as_dict(self) -> dict:
        return {
            "edge_id": self.edge_id,
            "chat_id": self.chat_id,
            "source_entity_id": self.source_entity_id,
            "target_entity_id": self.target_entity_id,
            "legacy_ids": list(self.legacy_ids),
            "relation_type": self.relation_type,
            "relation_label": self.relation_label,
            "direction": self.direction,
            "origin_class": self.origin_class.value,
            "has_unsupported_sources": self.has_unsupported_sources,
            "sources": [s.as_dict() for s in self.sources],
            "independent_support": self.independent_support,
            "legacy_sources_count": self.legacy_sources_count,
            "frequency": self.frequency,
            "status": self.status.value,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "last_confirmed": self.last_confirmed,
            "confidence_basis": self.confidence_basis,
            "explanation": self.explanation,
            "revision": {
                "graph": self.graph_revision,
                "edge_updated_at": self.edge_updated_at,
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RelationView":
        return cls(
            edge_id=data["edge_id"], chat_id=data["chat_id"],
            source_entity_id=data["source_entity_id"],
            target_entity_id=data["target_entity_id"],
            relation_type=data["relation_type"],
            relation_label=data["relation_label"],
            status=data["status"],
            sources=tuple(RelationSourceView.from_dict(s)
                          for s in data.get("sources") or ()),
            legacy_ids=tuple(data.get("legacy_ids") or ()),
            frequency=data.get("frequency", 1),
            explanation=data.get("explanation", LEGACY_EXPLANATION),
            valid_from=data.get("valid_from"),
            valid_to=data.get("valid_to"),
            last_confirmed=data.get("last_confirmed"),
            confidence_basis=data.get("confidence_basis"),
            graph_revision=(data.get("revision") or {}).get("graph", ""),
            edge_updated_at=(data.get("revision") or {}).get("edge_updated_at"),
        )


# ── C-3 §3.3.1: модальность только из реального сигнала ───────────────────

def resolve_assertion_mode(
    *,
    forwarded: bool = False,
    forward_from: str | None = None,
    perspective: str | None = None,
    attribution_method: str | None = None,
    provenance_channel: str | None = None,
    origin: str | None = None,
    denied: bool = False,
    hypothetical: bool = False,
    joking: bool = False,
) -> AssertionMode:
    """`assertion_mode` из существующих сигналов (§3.3.1), иначе `unknown`.

    Догадки по смайлику, кавычкам, восклицанию или длине сообщения запрещены
    (MEM-03.1/MEM-06.4): без сигнала возвращается `UNKNOWN`.
    """
    if forwarded or (forward_from or "").strip() or perspective == "quoted":
        return AssertionMode.QUOTED
    if perspective == "third_party" or attribution_method == "third_party":
        return AssertionMode.REPORTED
    if (provenance_channel in ("dream", "dossier_layer_a", "dossier_layer_b")
            or origin == "derived_belief"):
        return AssertionMode.INFERRED
    if denied:
        return AssertionMode.DENIED
    if perspective == "self" and attribution_method == "self_report":
        return AssertionMode.ASSERTED
    if hypothetical:
        return AssertionMode.HYPOTHETICAL
    if joking:
        return AssertionMode.JOKING
    return AssertionMode.UNKNOWN


# ── C-4: интент, выдача и ответ поиска ────────────────────────────────────

@dataclass(frozen=True)
class IntentHint:
    """Подсказка ранжированию (§4.2): не фильтр и не классификатор типа."""

    kind: str
    weight: float = 0.0

    def __post_init__(self) -> None:
        if self.kind not in _INTENT_KINDS:
            raise ValueError(
                f"IntentHint.kind invalid: {self.kind!r}; "
                f"allowed: {sorted(_INTENT_KINDS)}")
        if isinstance(self.weight, bool) or not isinstance(
                self.weight, (int, float)):
            raise ValueError("IntentHint.weight must be a number")
        if not 0.0 <= float(self.weight) <= 1.0:
            raise ValueError("IntentHint.weight must be within 0..1")

    def as_dict(self) -> dict:
        return {"kind": self.kind, "weight": float(self.weight)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IntentHint":
        return cls(kind=data["kind"], weight=data.get("weight", 0.0))


@dataclass(frozen=True)
class TimeHint:
    """Временная подсказка из `chat_clock` (§4.2); `tz_source` обязателен."""

    tz_source: str
    time_from: int | None = None
    time_to: int | None = None

    def __post_init__(self) -> None:
        _text(self.tz_source, "TimeHint.tz_source", maximum=64)
        _opt_ts(self.time_from, "TimeHint.time_from")
        _opt_ts(self.time_to, "TimeHint.time_to")
        if (self.time_from is not None and self.time_to is not None
                and self.time_from > self.time_to):
            raise ValueError("TimeHint.time_from must not be after time_to")

    def as_dict(self) -> dict:
        return {"from": self.time_from, "to": self.time_to,
                "tz_source": self.tz_source}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TimeHint":
        return cls(tz_source=data["tz_source"], time_from=data.get("from"),
                   time_to=data.get("to"))


@dataclass(frozen=True)
class SearchScope:
    """Область поиска/ответа (§4.3): чат либо разрешённый набор + `partial`."""

    mode: SearchScopeMode = SearchScopeMode.CHAT
    chat_id: int | None = None
    partial: bool = False

    def __post_init__(self) -> None:
        mode = _enum(SearchScopeMode, self.mode, "SearchScope.mode")
        if not isinstance(self.partial, bool):
            raise ValueError("SearchScope.partial must be bool")
        if mode is SearchScopeMode.CHAT:
            if self.chat_id is None:
                raise ValueError("SearchScope.mode='chat' requires chat_id")
            _chat_id(self.chat_id, "SearchScope.chat_id")
        else:
            if self.chat_id is not None:
                raise ValueError(
                    "SearchScope.mode='scope_all' must not pin one chat_id")
        _normalized(self, "mode", mode)

    def as_dict(self) -> dict:
        return {"chat_id": self.chat_id, "mode": self.mode.value,
                "partial": self.partial}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SearchScope":
        return cls(mode=data.get("mode", SearchScopeMode.CHAT),
                   chat_id=data.get("chat_id"),
                   partial=bool(data.get("partial", False)))


@dataclass(frozen=True)
class SearchIntent:
    """Серверный интент поиска (§4.2) — детерминированный, без LLM."""

    q: str
    scope: SearchScope
    mode: IntentMode
    intents: tuple[IntentHint, ...] = ()
    subjects: tuple[EntityRef, ...] = ()
    ambiguous_subjects: tuple[EntityResolution, ...] = ()
    terms: tuple[str, ...] = ()
    quoted: tuple[str, ...] = ()
    time_hint: TimeHint | None = None

    def __post_init__(self) -> None:
        _text(self.q, "SearchIntent.q", maximum=SEARCH_QUERY_MAX_CHARS)
        if not isinstance(self.scope, SearchScope):
            raise ValueError("SearchIntent.scope must be SearchScope")
        mode = _enum(IntentMode, self.mode, "SearchIntent.mode")
        intents = _tuple_of(self.intents, "SearchIntent.intents")
        for hint in intents:
            if not isinstance(hint, IntentHint):
                raise ValueError("SearchIntent.intents[] must be IntentHint")
        subjects = _tuple_of(self.subjects, "SearchIntent.subjects")
        for subject in subjects:
            if not isinstance(subject, EntityRef):
                raise ValueError("SearchIntent.subjects[] must be EntityRef")
            if subject.chat_id != self.scope.chat_id:
                if self.scope.mode is SearchScopeMode.CHAT:
                    raise ValueError(
                        "SearchIntent.subjects[] must belong to scope chat")
        ambiguous = _tuple_of(self.ambiguous_subjects,
                             "SearchIntent.ambiguous_subjects")
        for resolution in ambiguous:
            if not isinstance(resolution, EntityResolution):
                raise ValueError(
                    "SearchIntent.ambiguous_subjects[] must be "
                    "EntityResolution")
            if resolution.status is not EntityResolutionStatus.AMBIGUOUS:
                raise ValueError(
                    "ambiguous_subjects[] accepts only 'ambiguous' resolutions")
        terms = tuple(
            _text(t, "SearchIntent.terms[]", maximum=SEARCH_QUERY_MAX_CHARS)
            for t in _tuple_of(self.terms, "SearchIntent.terms"))
        quoted = tuple(
            _text(t, "SearchIntent.quoted[]", maximum=SEARCH_QUERY_MAX_CHARS)
            for t in _tuple_of(self.quoted, "SearchIntent.quoted"))
        if self.time_hint is not None and not isinstance(
                self.time_hint, TimeHint):
            raise ValueError("SearchIntent.time_hint must be TimeHint|None")
        _normalized(self, "mode", mode)
        _normalized(self, "intents", intents)
        _normalized(self, "subjects", subjects)
        _normalized(self, "ambiguous_subjects", ambiguous)
        _normalized(self, "terms", terms)
        _normalized(self, "quoted", quoted)

    def as_dict(self) -> dict:
        return {
            "q": self.q,
            "scope": self.scope.as_dict(),
            "intents": [h.as_dict() for h in self.intents],
            "subjects": [s.as_dict() for s in self.subjects],
            "ambiguous_subjects": [a.as_dict() for a in self.ambiguous_subjects],
            "terms": list(self.terms),
            "quoted": list(self.quoted),
            "time_hint": self.time_hint.as_dict() if self.time_hint else None,
            "mode": self.mode.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SearchIntent":
        time_hint = data.get("time_hint")
        return cls(
            q=data["q"], scope=SearchScope.from_dict(data["scope"]),
            mode=data["mode"],
            intents=tuple(IntentHint.from_dict(i)
                          for i in data.get("intents") or ()),
            subjects=tuple(EntityRef.from_dict(s)
                           for s in data.get("subjects") or ()),
            ambiguous_subjects=tuple(
                EntityResolution.from_dict(a)
                for a in data.get("ambiguous_subjects") or ()),
            terms=tuple(data.get("terms") or ()),
            quoted=tuple(data.get("quoted") or ()),
            time_hint=TimeHint.from_dict(time_hint) if time_hint else None,
        )


@dataclass(frozen=True)
class SearchRevision:
    """Эхо ревизии чтения (§2.4.3): токен консистентности, не ключ записи."""

    graph: str
    alias: str
    index_fingerprint: str
    community_build: str | None = None

    def __post_init__(self) -> None:
        _text(self.graph, "SearchRevision.graph", maximum=128)
        _text(self.alias, "SearchRevision.alias", maximum=128)
        _text(self.index_fingerprint, "SearchRevision.index_fingerprint",
              maximum=128)
        if self.community_build is not None:
            _text(self.community_build, "SearchRevision.community_build",
                  maximum=128)

    def as_dict(self) -> dict:
        return {"graph": self.graph, "alias": self.alias,
                "community_build": self.community_build,
                "index_fingerprint": self.index_fingerprint}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SearchRevision":
        return cls(graph=data["graph"], alias=data["alias"],
                   index_fingerprint=data["index_fingerprint"],
                   community_build=data.get("community_build"))


@dataclass(frozen=True)
class SearchFocus:
    """Куда навести карту; `None` у факта без узла — честно (§4.3)."""

    chat_id: int
    node_id: int

    def __post_init__(self) -> None:
        _chat_id(self.chat_id, "SearchFocus.chat_id")
        _int(self.node_id, "SearchFocus.node_id", minimum=1)

    def as_dict(self) -> dict:
        return {"chat_id": self.chat_id, "node_id": self.node_id}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SearchFocus":
        return cls(chat_id=data["chat_id"], node_id=data["node_id"])


@dataclass(frozen=True)
class SearchVariant:
    """Вариант при неоднозначности выдачи (S-5): популярный не выбирается."""

    canonical_id: str
    title: str
    discriminator: str

    def __post_init__(self) -> None:
        _canonical_id(self.canonical_id, "SearchVariant.canonical_id")
        _human_text(self.title, "SearchVariant.title", maximum=200)
        _text(self.discriminator, "SearchVariant.discriminator", maximum=200)

    def as_dict(self) -> dict:
        return {"canonical_id": self.canonical_id, "title": self.title,
                "discriminator": self.discriminator}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SearchVariant":
        return cls(canonical_id=data["canonical_id"], title=data["title"],
                   discriminator=data["discriminator"])


@dataclass(frozen=True)
class SearchAmbiguity:
    """Явная неоднозначность выдачи: ≥2 варианта с различающим признаком."""

    reason: str
    variants: tuple[SearchVariant, ...]

    def __post_init__(self) -> None:
        _text(self.reason, "SearchAmbiguity.reason", maximum=200)
        variants = _tuple_of(self.variants, "SearchAmbiguity.variants")
        for variant in variants:
            if not isinstance(variant, SearchVariant):
                raise ValueError(
                    "SearchAmbiguity.variants[] must be SearchVariant")
        if len(variants) < 2:
            raise ValueError("SearchAmbiguity requires >= 2 variants (S-5)")
        _normalized(self, "variants", variants)

    def as_dict(self) -> dict:
        return {"reason": self.reason,
                "variants": [v.as_dict() for v in self.variants]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SearchAmbiguity":
        return cls(reason=data["reason"],
                   variants=tuple(SearchVariant.from_dict(v)
                                  for v in data["variants"]))


def _canonical_id(value: Any, field_name: str) -> str:
    text = _text(value, field_name, maximum=200)
    if not _CANONICAL_RE.match(text):
        raise ValueError(f"{field_name} must be canonical id, got {text!r}")
    return text


@dataclass(frozen=True)
class SearchItem:
    """Элемент выдачи поиска (§4.3); рендер не требует текста переписки.

    `snippet` ограничен разделяемой константой `preview_max_chars()` и не
    содержит внутренних id/метрик (S-7, R17).
    """

    ref_kind: RefKind
    canonical_id: str
    title: str
    category: str
    match_cause: MatchCause
    evidence_status: EvidenceStatus
    legacy_ids: tuple[str, ...] = ()
    snippet: str | None = None
    event_ts: int | None = None
    observed_ts: int | None = None
    focus: SearchFocus | None = None
    ambiguity: SearchAmbiguity | None = None

    def __post_init__(self) -> None:
        kind = _enum(RefKind, self.ref_kind, "SearchItem.ref_kind")
        canonical_id = _canonical_id(self.canonical_id, "SearchItem.canonical_id")
        prefix = _CANONICAL_PREFIX[kind]
        if not canonical_id.startswith(f"{prefix}:"):
            raise ValueError(
                f"SearchItem.canonical_id must start with {prefix + ':'!r} for "
                f"ref_kind={kind.value!r}")
        _human_text(self.title, "SearchItem.title", maximum=200)
        if self.category not in CATEGORIES:
            raise ValueError(
                f"SearchItem.category invalid: {self.category!r}; allowed: "
                f"{sorted(CATEGORIES)}")
        cause = _enum(MatchCause, self.match_cause, "SearchItem.match_cause")
        evidence = _enum(EvidenceStatus, self.evidence_status,
                         "SearchItem.evidence_status")
        legacy_ids = tuple(
            _canonical_id(v, "SearchItem.legacy_ids[]")
            for v in _tuple_of(self.legacy_ids, "SearchItem.legacy_ids"))
        if self.snippet is not None:
            limit = preview_max_chars()
            _human_text(self.snippet, "SearchItem.snippet", maximum=limit)
        _opt_ts(self.event_ts, "SearchItem.event_ts")
        _opt_ts(self.observed_ts, "SearchItem.observed_ts")
        if self.focus is not None and not isinstance(self.focus, SearchFocus):
            raise ValueError("SearchItem.focus must be SearchFocus|None")
        if self.ambiguity is not None and not isinstance(
                self.ambiguity, SearchAmbiguity):
            raise ValueError("SearchItem.ambiguity must be SearchAmbiguity|None")
        _normalized(self, "ref_kind", kind)
        _normalized(self, "canonical_id", canonical_id)
        _normalized(self, "match_cause", cause)
        _normalized(self, "evidence_status", evidence)
        _normalized(self, "legacy_ids", legacy_ids)

    def as_dict(self) -> dict:
        return {
            "ref_kind": self.ref_kind.value,
            "canonical_id": self.canonical_id,
            "legacy_ids": list(self.legacy_ids),
            "title": self.title,
            "category": self.category,
            "snippet": self.snippet,
            "match_cause": self.match_cause.value,
            "evidence_status": self.evidence_status.value,
            "event_ts": self.event_ts,
            "observed_ts": self.observed_ts,
            "focus": self.focus.as_dict() if self.focus else None,
            "ambiguity": self.ambiguity.as_dict() if self.ambiguity else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SearchItem":
        focus = data.get("focus")
        ambiguity = data.get("ambiguity")
        return cls(
            ref_kind=data["ref_kind"], canonical_id=data["canonical_id"],
            title=data["title"], category=data["category"],
            match_cause=data["match_cause"],
            evidence_status=data["evidence_status"],
            legacy_ids=tuple(data.get("legacy_ids") or ()),
            snippet=data.get("snippet"),
            event_ts=data.get("event_ts"),
            observed_ts=data.get("observed_ts"),
            focus=SearchFocus.from_dict(focus) if focus else None,
            ambiguity=(SearchAmbiguity.from_dict(ambiguity)
                       if ambiguity else None),
        )


@dataclass(frozen=True)
class SearchResponse:
    """Ответ поиска (§4.3/§4.9): явные исходы, курсор и эхо ревизии.

    `status` — технический исход, `query_state` — пользовательское состояние;
    пара проверяется по взаимоисключающей матрице. «Пусто» никогда не
    подменяет «нет прав», «ошибку» или устаревший курсор (S-4/S-9).
    """

    status: SearchStatus
    query_state: QueryState
    revision: SearchRevision
    generation: int
    scope: SearchScope
    items: tuple[SearchItem, ...] = ()
    next_cursor: str | None = None
    has_more: bool = False
    reason_code: str | None = None
    debug: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        status = _enum(SearchStatus, self.status, "SearchResponse.status")
        state = _enum(QueryState, self.query_state,
                      "SearchResponse.query_state")
        allowed = _OUTCOME_MATRIX[status]
        if state not in allowed:
            raise ValueError(
                f"query_state={state.value!r} is not a valid outcome for "
                f"status={status.value!r}; allowed: "
                f"{sorted(s.value for s in allowed)}")
        if not isinstance(self.revision, SearchRevision):
            raise ValueError("SearchResponse.revision must be SearchRevision")
        _int(self.generation, "SearchResponse.generation", minimum=0)
        if not isinstance(self.scope, SearchScope):
            raise ValueError("SearchResponse.scope must be SearchScope")
        items = _tuple_of(self.items, "SearchResponse.items")
        for item in items:
            if not isinstance(item, SearchItem):
                raise ValueError("SearchResponse.items[] must be SearchItem")
        if self.next_cursor is not None:
            _text(self.next_cursor, "SearchResponse.next_cursor", maximum=512)
        if not isinstance(self.has_more, bool):
            raise ValueError("SearchResponse.has_more must be bool")
        reason_code = None if self.reason_code is None else _text(
            self.reason_code, "SearchResponse.reason_code", maximum=64)
        if self.debug is not None and not isinstance(self.debug, Mapping):
            raise ValueError("SearchResponse.debug must be a mapping|None")

        if self.has_more and self.next_cursor is None:
            raise ValueError("has_more=True requires next_cursor")
        if self.next_cursor is not None and not self.has_more:
            raise ValueError("next_cursor requires has_more=True")

        if status in (SearchStatus.OK, SearchStatus.AMBIGUOUS,
                      SearchStatus.LEGACY_ONLY, SearchStatus.PARTIAL):
            if not items:
                raise ValueError(
                    f"status={status.value!r} requires at least one item")
        if status in (SearchStatus.EMPTY, SearchStatus.FORBIDDEN,
                      SearchStatus.ERROR, SearchStatus.CURSOR_STALE):
            if items:
                raise ValueError(
                    f"status={status.value!r} must not carry items")
            if self.next_cursor is not None or self.has_more:
                raise ValueError(
                    f"status={status.value!r} must not paginate")
        if status is SearchStatus.CURSOR_STALE:
            if reason_code != _STALE_CURSOR_REASON:
                raise ValueError(
                    "cursor_stale requires reason_code="
                    f"{_STALE_CURSOR_REASON!r} (§4.9)")
        if status is SearchStatus.AMBIGUOUS:
            if not any(item.ambiguity is not None for item in items):
                raise ValueError(
                    "status='ambiguous' requires an item with ambiguity")
        if status is SearchStatus.LEGACY_ONLY:
            for item in items:
                if item.evidence_status is EvidenceStatus.CONFIRMED:
                    raise ValueError(
                        "legacy_only response must not carry confirmed items")
        if status is SearchStatus.PARTIAL and not self.scope.partial:
            raise ValueError("status='partial' requires scope.partial=True")
        if status is not SearchStatus.PARTIAL and self.scope.partial:
            if status not in (SearchStatus.OK, SearchStatus.CURSOR_STALE):
                raise ValueError(
                    "scope.partial=True only for partial/ok/cursor_stale")

        _normalized(self, "status", status)
        _normalized(self, "query_state", state)
        _normalized(self, "items", items)
        _normalized(self, "reason_code", reason_code)

    def as_dict(self) -> dict:
        return {
            "status": self.status.value,
            "reason_code": self.reason_code,
            "query_state": self.query_state.value,
            "items": [item.as_dict() for item in self.items],
            "next_cursor": self.next_cursor,
            "has_more": self.has_more,
            "generation": self.generation,
            "scope": self.scope.as_dict(),
            "revision": self.revision.as_dict(),
            "debug": dict(self.debug) if self.debug is not None else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SearchResponse":
        return cls(
            status=data["status"], query_state=data["query_state"],
            revision=SearchRevision.from_dict(data["revision"]),
            generation=data["generation"],
            scope=SearchScope.from_dict(data["scope"]),
            items=tuple(SearchItem.from_dict(i)
                        for i in data.get("items") or ()),
            next_cursor=data.get("next_cursor"),
            has_more=bool(data.get("has_more", False)),
            reason_code=data.get("reason_code"),
            debug=data.get("debug"),
        )


# ── C-7/C-8: краткоживущее представление выборки (не хранилище) ───────────

@dataclass(frozen=True)
class MemoryViewRef:
    """Ссылка выборки: ранг и причина отбора (§2.6 пользовательского ТЗ)."""

    canonical_id: str
    ref_kind: RefKind
    rank: int
    selection_reason: str
    evidence_status: EvidenceStatus = EvidenceStatus.UNKNOWN

    def __post_init__(self) -> None:
        canonical_id = _canonical_id(self.canonical_id,
                                     "MemoryViewRef.canonical_id")
        kind = _enum(RefKind, self.ref_kind, "MemoryViewRef.ref_kind")
        prefix = _CANONICAL_PREFIX[kind]
        if not canonical_id.startswith(f"{prefix}:"):
            raise ValueError(
                f"MemoryViewRef.canonical_id must start with {prefix + ':'!r} "
                f"for ref_kind={kind.value!r}")
        _int(self.rank, "MemoryViewRef.rank", minimum=1)
        _text(self.selection_reason, "MemoryViewRef.selection_reason",
              maximum=200)
        evidence = _enum(EvidenceStatus, self.evidence_status,
                         "MemoryViewRef.evidence_status")
        _normalized(self, "canonical_id", canonical_id)
        _normalized(self, "ref_kind", kind)
        _normalized(self, "evidence_status", evidence)

    def as_dict(self) -> dict:
        return {"canonical_id": self.canonical_id,
                "ref_kind": self.ref_kind.value, "rank": self.rank,
                "selection_reason": self.selection_reason,
                "evidence_status": self.evidence_status.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MemoryViewRef":
        return cls(canonical_id=data["canonical_id"],
                   ref_kind=data["ref_kind"], rank=data["rank"],
                   selection_reason=data["selection_reason"],
                   evidence_status=data.get("evidence_status", "unknown"))


@dataclass(frozen=True)
class MemoryView:
    """Результат одной выборки памяти для ответа/инициативы/сна/карты.

    Контракт §2.6 пользовательского ТЗ: ссылки, ранги и причины отбора; это
    **не** хранилище правды и не вторая память. Побочных эффектов и записи нет.
    """

    purpose: MemoryPurpose
    refs: tuple[MemoryViewRef, ...] = ()
    partial: bool = False

    def __post_init__(self) -> None:
        purpose = _enum(MemoryPurpose, self.purpose, "MemoryView.purpose")
        refs = _tuple_of(self.refs, "MemoryView.refs")
        for ref in refs:
            if not isinstance(ref, MemoryViewRef):
                raise ValueError("MemoryView.refs[] must be MemoryViewRef")
        ranks = [ref.rank for ref in refs]
        if ranks != list(range(1, len(refs) + 1)):
            raise ValueError(
                "MemoryView.refs ranks must be 1..N in order (deterministic)")
        if not isinstance(self.partial, bool):
            raise ValueError("MemoryView.partial must be bool")
        _normalized(self, "purpose", purpose)
        _normalized(self, "refs", refs)

    def as_dict(self) -> dict:
        return {"purpose": self.purpose.value,
                "refs": [ref.as_dict() for ref in self.refs],
                "partial": self.partial}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MemoryView":
        return cls(purpose=data["purpose"],
                   refs=tuple(MemoryViewRef.from_dict(r)
                              for r in data.get("refs") or ()),
                   partial=bool(data.get("partial", False)))


# ── C-8 §8: атрибуция «кто сказал / о ком / кому», медиа и опыт ─────────────


@dataclass(frozen=True)
class AddresseeResolution:
    """Результат определения адресата (§8.2). Нечестные состояния запрещены.

    * `RESOLVED` требует самого адресата и НЕНУЛЕВОГО сигнала;
    * `AMBIGUOUS` не несёт адресата вовсе, но несёт ≥2 кандидата;
    * `UNKNOWN` не несёт ни адресата, ни сигнала.

    Поэтому «неоднозначность, превращённая в резолв» и «выдуманный адресат»
    невозможны конструктором, а не соглашением.
    """

    status: AddresseeStatus
    addressee: str | None = None
    basis: AddresseeBasis = AddresseeBasis.NONE
    candidates: tuple[str, ...] = ()
    reason_code: str = ""

    def __post_init__(self) -> None:
        status = _enum(AddresseeStatus, self.status,
                       "AddresseeResolution.status")
        basis = _enum(AddresseeBasis, self.basis, "AddresseeResolution.basis")
        addressee = None
        if self.addressee is not None:
            addressee = _text(self.addressee, "AddresseeResolution.addressee",
                              maximum=ENTITY_MENTION_MAX_CHARS)
        candidates: list[str] = []
        for value in _tuple_of(self.candidates,
                               "AddresseeResolution.candidates"):
            cleaned = _text(value, "AddresseeResolution.candidates[]",
                            maximum=ENTITY_MENTION_MAX_CHARS)
            if cleaned not in candidates:
                candidates.append(cleaned)
        reason = _text(self.reason_code, "AddresseeResolution.reason_code",
                       maximum=64, allow_empty=True)
        if status is AddresseeStatus.RESOLVED:
            if addressee is None:
                raise ValueError(
                    "resolved addressee requires addressee (§8.2)")
            if basis is AddresseeBasis.NONE:
                raise ValueError(
                    "resolved addressee requires a real signal basis (§8.2)")
        elif status is AddresseeStatus.AMBIGUOUS:
            if addressee is not None:
                raise ValueError(
                    "ambiguous addressee must not pick a recipient (§8.2)")
            if len(candidates) < 2:
                raise ValueError(
                    "ambiguous addressee requires >=2 candidates (§8.2)")
        else:                                     # UNKNOWN
            if addressee is not None:
                raise ValueError(
                    "unknown addressee must not invent a recipient (§8.2)")
            if basis is not AddresseeBasis.NONE:
                raise ValueError(
                    "unknown addressee must not claim a signal basis (§8.2)")
        _normalized(self, "status", status)
        _normalized(self, "basis", basis)
        _normalized(self, "addressee", addressee)
        _normalized(self, "candidates", tuple(candidates))
        _normalized(self, "reason_code", reason)

    def as_dict(self) -> dict:
        return {"status": self.status.value,
                "addressee": self.addressee,
                "basis": self.basis.value,
                "candidates": list(self.candidates),
                "reason_code": self.reason_code}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AddresseeResolution":
        return cls(status=data["status"],
                   addressee=data.get("addressee"),
                   basis=data.get("basis", AddresseeBasis.NONE),
                   candidates=tuple(data.get("candidates") or ()),
                   reason_code=data.get("reason_code") or "")


@dataclass(frozen=True)
class StatementAttribution:
    """Атрибуция запомненного утверждения (§8.2…§8.4, MEM-05.1/05.2/05.4).

    Раздельные слоты, которые нельзя склеить:

    * `speaker`/`speaker_user_id` — кто произнёс (отправитель);
    * `content_author` — чьи это слова: для пересылки это ПЕРВОИСТОЧНИК
      (R-9), а не переславший; неизвестен — `None`, а не переславший;
    * `subject` — о ком/о чём утверждение;
    * адресат (`addressee*`) — состояние `AddresseeResolution` в плоском виде;
    * `modality` — модальность из реальных сигналов (§3.3.1);
    * `source_message_id`/`source_ref` — событие-источник.

    Собственный вывод бота (`speaker_kind=BOT`) не подтверждает внешний факт:
    `corroborates=True` для него невозможно.
    """

    chat_id: int
    speaker_kind: SpeakerKind = SpeakerKind.UNKNOWN
    modality: AssertionMode = AssertionMode.UNKNOWN
    speaker: str | None = None
    speaker_user_id: int | None = None
    subject: str | None = None
    addressee: str | None = None
    addressee_status: AddresseeStatus = AddresseeStatus.UNKNOWN
    addressee_basis: AddresseeBasis = AddresseeBasis.NONE
    addressee_candidates: tuple[str, ...] = ()
    forwarded: bool = False
    content_author: str | None = None
    content_author_user_id: int | None = None
    quoted_author: str | None = None
    source_message_id: int | None = None
    source_ref: str | None = None
    corroborates: bool = True
    reason_code: str = ""

    def __post_init__(self) -> None:
        _chat_id(self.chat_id, "StatementAttribution.chat_id")
        kind = _enum(SpeakerKind, self.speaker_kind,
                     "StatementAttribution.speaker_kind")
        modality = _enum(AssertionMode, self.modality,
                         "StatementAttribution.modality")
        status = _enum(AddresseeStatus, self.addressee_status,
                       "StatementAttribution.addressee_status")
        basis = _enum(AddresseeBasis, self.addressee_basis,
                      "StatementAttribution.addressee_basis")
        for name in ("speaker", "subject", "content_author", "quoted_author",
                     "addressee"):
            value = getattr(self, name)
            if value is not None:
                _text(value, f"StatementAttribution.{name}",
                      maximum=ENTITY_MENTION_MAX_CHARS)
        if self.speaker_user_id is not None:
            _int(self.speaker_user_id, "StatementAttribution.speaker_user_id",
                 minimum=1)
        if self.content_author_user_id is not None:
            _int(self.content_author_user_id,
                 "StatementAttribution.content_author_user_id", minimum=1)
        candidates: list[str] = []
        for value in _tuple_of(self.addressee_candidates,
                               "StatementAttribution.addressee_candidates"):
            cleaned = _text(value,
                            "StatementAttribution.addressee_candidates[]",
                            maximum=ENTITY_MENTION_MAX_CHARS)
            if cleaned not in candidates:
                candidates.append(cleaned)
        if self.source_message_id is not None:
            _int(self.source_message_id,
                 "StatementAttribution.source_message_id", minimum=1)
        if self.source_ref is not None:
            _text(self.source_ref, "StatementAttribution.source_ref",
                  maximum=128)
        if not isinstance(self.forwarded, bool):
            raise ValueError("StatementAttribution.forwarded must be bool")
        if not isinstance(self.corroborates, bool):
            raise ValueError("StatementAttribution.corroborates must be bool")
        reason = _text(self.reason_code, "StatementAttribution.reason_code",
                       maximum=64, allow_empty=True)
        # §8.4/R-3: self-output не подтверждает внешний факт.
        if kind is SpeakerKind.BOT and self.corroborates:
            raise ValueError(
                "bot self-statement must not corroborate an external fact "
                "(§8.4/R-3)")
        # §8.2: адресат описывается тем же закрытым контрактом.
        if status is AddresseeStatus.RESOLVED:
            if self.addressee is None or basis is AddresseeBasis.NONE:
                raise ValueError(
                    "resolved addressee requires addressee and a real signal "
                    "basis (§8.2)")
        elif status is AddresseeStatus.AMBIGUOUS:
            if self.addressee is not None or len(candidates) < 2:
                raise ValueError(
                    "ambiguous addressee must not pick a recipient and "
                    "requires >=2 candidates (§8.2)")
        else:                                     # UNKNOWN
            if self.addressee is not None or basis is not AddresseeBasis.NONE:
                raise ValueError(
                    "unknown addressee must not invent a recipient or a "
                    "signal basis (§8.2)")
        # §8.2/R-9: без пересылки «слова» принадлежат говорящему; для
        # пересылки content_author — только первоисточник (или unknown).
        if not self.forwarded and self.content_author is not None \
                and self.content_author != self.speaker:
            raise ValueError(
                "content_author of a non-forwarded statement must equal the "
                "speaker (§8.2/R-9)")
        if not self.forwarded and self.content_author_user_id is not None \
                and self.content_author_user_id != self.speaker_user_id:
            raise ValueError(
                "content_author_user_id of a non-forwarded statement must "
                "equal the speaker (§8.2/R-9)")
        _normalized(self, "speaker_kind", kind)
        _normalized(self, "modality", modality)
        _normalized(self, "addressee_status", status)
        _normalized(self, "addressee_basis", basis)
        _normalized(self, "addressee_candidates", tuple(candidates))
        _normalized(self, "reason_code", reason)

    @property
    def attributed_author(self) -> str | None:
        """Чьи это слова: первоисточник пересылки либо говорящий.

        Для пересылки без известного первоисточника — `None` (unknown):
        переславший автором не становится (R-9)."""
        if self.forwarded:
            return self.content_author
        return self.speaker or self.content_author

    @property
    def addressee_resolution(self) -> AddresseeResolution:
        return AddresseeResolution(
            status=self.addressee_status, addressee=self.addressee,
            basis=self.addressee_basis, candidates=self.addressee_candidates)

    def as_dict(self) -> dict:
        return {"chat_id": self.chat_id,
                "speaker": self.speaker,
                "speaker_user_id": self.speaker_user_id,
                "speaker_kind": self.speaker_kind.value,
                "subject": self.subject,
                "modality": self.modality.value,
                "addressee": self.addressee,
                "addressee_status": self.addressee_status.value,
                "addressee_basis": self.addressee_basis.value,
                "addressee_candidates": list(self.addressee_candidates),
                "forwarded": self.forwarded,
                "content_author": self.content_author,
                "content_author_user_id": self.content_author_user_id,
                "quoted_author": self.quoted_author,
                "source_message_id": self.source_message_id,
                "source_ref": self.source_ref,
                "corroborates": self.corroborates,
                "reason_code": self.reason_code}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StatementAttribution":
        return cls(
            chat_id=data["chat_id"],
            speaker_kind=data.get("speaker_kind", SpeakerKind.UNKNOWN),
            modality=data.get("modality", AssertionMode.UNKNOWN),
            speaker=data.get("speaker"),
            speaker_user_id=data.get("speaker_user_id"),
            subject=data.get("subject"),
            addressee=data.get("addressee"),
            addressee_status=data.get("addressee_status",
                                       AddresseeStatus.UNKNOWN),
            addressee_basis=data.get("addressee_basis", AddresseeBasis.NONE),
            addressee_candidates=tuple(data.get("addressee_candidates") or ()),
            forwarded=bool(data.get("forwarded", False)),
            content_author=data.get("content_author"),
            content_author_user_id=data.get("content_author_user_id"),
            quoted_author=data.get("quoted_author"),
            source_message_id=data.get("source_message_id"),
            source_ref=data.get("source_ref"),
            corroborates=bool(data.get("corroborates", True)),
            reason_code=data.get("reason_code") or "")


@dataclass(frozen=True)
class MediaMemoryAttribution:
    """Запомненная выжимка медиа (§8.5, MEM-05.5/05.6).

    Переносится только ФАКТИЧЕСКИ выполненное понимание с идентификатором
    исходного медиа, временем, статусом распознавания и областью видимости.
    `description` при `NOT_PROCESSED`/`UNAVAILABLE` невозможен конструктором:
    «не обработано» не может читаться как понимание.
    """

    chat_id: int
    media_asset_id: str
    vision_status: MediaVisionStatus = MediaVisionStatus.NOT_PROCESSED
    timestamp: int | None = None
    transcription_status: MediaVisionStatus = MediaVisionStatus.NOT_PROCESSED
    description: str | None = None
    media_type: str | None = None
    tg_message_id: int | None = None
    access_scope: str | None = None
    analysis_revision: int | None = None
    reason_code: str = "unknown"

    def __post_init__(self) -> None:
        _chat_id(self.chat_id, "MediaMemoryAttribution.chat_id")
        _text(self.media_asset_id, "MediaMemoryAttribution.media_asset_id",
              maximum=128)
        vision = _enum(MediaVisionStatus, self.vision_status,
                       "MediaMemoryAttribution.vision_status")
        transcription = _enum(
            MediaVisionStatus, self.transcription_status,
            "MediaMemoryAttribution.transcription_status")
        _opt_ts(self.timestamp, "MediaMemoryAttribution.timestamp")
        description = None
        if self.description is not None:
            description = _text(self.description,
                                "MediaMemoryAttribution.description",
                                maximum=2000)
        if description is not None and vision is not MediaVisionStatus.PROCESSED:
            raise ValueError(
                "media description requires vision_status='processed' (§8.5)")
        if self.media_type is not None:
            _text(self.media_type, "MediaMemoryAttribution.media_type",
                  maximum=32)
        if self.tg_message_id is not None:
            _int(self.tg_message_id, "MediaMemoryAttribution.tg_message_id",
                 minimum=1)
        if self.access_scope is not None:
            _text(self.access_scope, "MediaMemoryAttribution.access_scope",
                  maximum=64)
        if self.analysis_revision is not None:
            _int(self.analysis_revision,
                 "MediaMemoryAttribution.analysis_revision", minimum=1)
        reason = _text(self.reason_code, "MediaMemoryAttribution.reason_code",
                       maximum=64)
        if reason not in MEDIA_MEMORY_REASONS:
            raise ValueError(
                f"MediaMemoryAttribution.reason_code invalid: {reason!r}; "
                f"allowed: {sorted(MEDIA_MEMORY_REASONS)}")
        _normalized(self, "vision_status", vision)
        _normalized(self, "transcription_status", transcription)
        _normalized(self, "description", description)
        _normalized(self, "reason_code", reason)

    @property
    def understood(self) -> bool:
        """Понимание содержимого ДОКАЗАНО только статусом `processed`."""
        return self.vision_status is MediaVisionStatus.PROCESSED

    @property
    def has_content(self) -> bool:
        return bool(self.description)

    def as_evidence(self) -> dict | None:
        """Свидетельство для памяти: `None`, если понимания не было."""
        if not self.understood:
            return None
        return {"media_asset_id": self.media_asset_id,
                "timestamp": self.timestamp,
                "vision_status": self.vision_status.value,
                "description": self.description,
                "media_type": self.media_type,
                "tg_message_id": self.tg_message_id,
                "access_scope": self.access_scope}

    def as_dict(self) -> dict:
        return {"chat_id": self.chat_id,
                "media_asset_id": self.media_asset_id,
                "vision_status": self.vision_status.value,
                "timestamp": self.timestamp,
                "transcription_status": self.transcription_status.value,
                "description": self.description,
                "media_type": self.media_type,
                "tg_message_id": self.tg_message_id,
                "access_scope": self.access_scope,
                "analysis_revision": self.analysis_revision,
                "reason_code": self.reason_code}


@dataclass(frozen=True)
class ExperienceVerdict:
    """Стабильность вывода опыта (§8.6, MEM-05.7).

    `STABLE` требует доказанной базы: `required_outcomes >= 1` и либо прямого
    указания/проверенного фикса (`basis`), либо ≥ требуемого числа независимых
    исходов. Одна неудача постоянным правилом не становится — это свойство
    конструктора, а не соглашение.
    """

    stability: ExperienceStability
    reason_code: str
    basis: str = "independent_outcomes"
    independent_outcomes: int = 0
    required_outcomes: int = 0

    def __post_init__(self) -> None:
        stability = _enum(ExperienceStability, self.stability,
                          "ExperienceVerdict.stability")
        reason = _text(self.reason_code, "ExperienceVerdict.reason_code",
                       maximum=64)
        if not isinstance(self.basis, str) \
                or self.basis not in EXPERIENCE_BASES:
            raise ValueError(
                f"ExperienceVerdict.basis invalid: {self.basis!r}; "
                f"allowed: {sorted(EXPERIENCE_BASES)}")
        _int(self.independent_outcomes, "ExperienceVerdict.independent_outcomes")
        _int(self.required_outcomes, "ExperienceVerdict.required_outcomes")
        if stability is ExperienceStability.STABLE:
            if self.required_outcomes < 1:
                raise ValueError(
                    "stable verdict requires required_outcomes >= 1 (§8.6)")
            if self.basis == "independent_outcomes" \
                    and self.independent_outcomes < self.required_outcomes:
                raise ValueError(
                    "stable verdict requires independent_outcomes >= "
                    "required_outcomes (§8.6)")
        _normalized(self, "stability", stability)
        _normalized(self, "reason_code", reason)

    @property
    def is_stable(self) -> bool:
        return self.stability is ExperienceStability.STABLE

    def as_dict(self) -> dict:
        return {"stability": self.stability.value,
                "reason_code": self.reason_code,
                "basis": self.basis,
                "independent_outcomes": self.independent_outcomes,
                "required_outcomes": self.required_outcomes}
