"""EPIC-MEMORY-COGNITIVE-02 / MEMORY-07 — семантические сообщества (C-6).

Источник: `plans/features/memory-cognitive-02/contracts.md` §0.5 (аддитивная
схема: `v43` = идентичность, `v44` = сообщества), §5.1 (`v44`: раскладка
таблиц, DDL владельца, идемпотентность и инертность) и §6 (C-6: веса рёбер,
членство, жизненный цикл сборки, чтение только `active`, стабильность
`community_id`).

Что здесь есть:

* **DDL владельца** таблиц сообществ (`v44`): `mca_community_builds`
  (реестр сборок) и `mca_community_members` (версионное членство) плюс их
  индексы. Миграция `services/database.py::_migrate_communities_v44`
  применяет ровно эти выражения — второй копии DDL в репозитории нет.
* **Детерминированный сборщик** (`build_chat_communities`) по полному
  chat scope: читает `nodes`/`edges`/`graph_facts`/`mca_associations` только
  на чтение, схлопывает идентичность через существующий
  `services/entity_resolver.py::resolve_entity` (read-only, §1.4.2) и считает
  сообщества на реальных взвешенных связях. Ни одна таблица памяти
  (`nodes`/`edges`/`graph_facts`/`mca_associations`/статусы) не меняется.
* **Веса §6**: `confirmed` = 1.0, `tentative` = 0.5, `legacy` = 0.25,
  `cooccurrence` = 0.1. Класс факта берётся ТОЛЬКО из существующего
  `services/graphrag_provenance.py::classify_fact_provenance`
  (`confident` → confirmed, `tentative` → tentative, `legacy_unverified` →
  legacy); `mca_associations` всегда `cooccurrence` и никогда не повышается
  до подтверждённого ребра (§2.2/§6, MEM-07.6).
* **Жизненный цикл сборки** (§6): `building → active`; `active → superseded`
  только атомарно, в одной транзакции с публикацией ПОЛНОГО набора членства;
  `building → failed` при исключении, отмене, нарушении инварианта или
  неполной публикации. Для чата допускается ровно один `active`; `failed` не
  читается и не вытесняет предыдущий `active`; `prev_build_id` связывает
  rebuild с предыдущей сборкой; `build_id` не меняется при retry, retry после
  `failed` создаёт новый `build_id`, а стабильность относится к
  `community_id`.
* **Подписи §6/MEM-07.4**: из реально доминирующих сущностей с источниками,
  иначе нейтральное «Сообщество N» + «как сформировано». LLM-наименований
  нет, на горячем пути ничего не вызывается. Колонки подписи в схеме нет
  (§5.1 запрещает новые колонки), поэтому подпись — вычисляемое значение
  результата сборки и той же чистой функцией читается API-слоем.

Границы (проверяется ревью, §0.5/§6): нет второго хранилища, нет второго
поиска, нет новых колонок в `nodes`/`edges`/`graph_facts`, нет таблицы
доказательств/чекпоинтов/кэша поиска в БД, нет LLM-наименований. Членство
хранит только канонический `nodes.id`; Telegram UID сюда не пишется и не
смешивается с `subject_entity_ids` MEMORY-06.

Инертность: шаг `v44` применяется безусловно при старте (как `v43`) —
таблицы существуют всегда, но без гейта `MCA_MEMORY_COMMUNITIES_ENABLED`
(реестр гейтов, default **OFF**) их никто не читает и не пишет: миграция
ничего не backfill'ит, старый код таблиц не знает. Гейт резолвит вызывающий
(регистрация job — волна 3, active-build join в retrieval — волна 4);
сборщик сам гейт не читает, чтобы в проекте не появился второй механизм
резолва гейтов. Откат — поведенческий (гейт OFF / предыдущий релиз), `DROP`
не требуется.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time
import uuid
from typing import Any, Mapping, Sequence

from services import entity_resolver
from services import graphrag_provenance as provenance
from services import mca_events
from services import memory_contracts as mc
from services.relation_evidence import graph_revision as _graph_revision
from services.relation_evidence import parse_edge_timestamp

logger = logging.getLogger(__name__)

#: Аддитивные таблицы сообществ (миграция `v44`).
COMMUNITY_BUILDS_TABLE = "mca_community_builds"
COMMUNITY_MEMBERS_TABLE = "mca_community_members"
#: Стабильное имя шага миграции (книга `schema_migrations`).
COMMUNITIES_MIGRATION_STEP_NAME = "memory_communities_v44"

#: DDL владельца реестра сборок — применяет миграция `v44`
#: (`services/database.py`) и тесты. `CREATE ... IF NOT EXISTS`: повторный
#: прогон — no-op, `ALTER` не нужен, существующие таблицы не меняются
#: (§5.1). `graph_revision` — строковый снимок вычисленной ревизии на момент
#: сборки, а не ссылка на несуществующую колонку.
COMMUNITY_BUILDS_DDL_SQLITE: tuple[str, ...] = (
    f"CREATE TABLE IF NOT EXISTS {COMMUNITY_BUILDS_TABLE} ("
    "build_id            TEXT PRIMARY KEY, "
    "chat_id             INTEGER NOT NULL, "
    "algorithm           TEXT NOT NULL, "
    "algorithm_version   TEXT NOT NULL, "
    "params_json         TEXT NOT NULL DEFAULT '{}', "
    "graph_revision      TEXT NOT NULL, "
    "node_count          INTEGER NOT NULL, "
    "edge_count          INTEGER NOT NULL, "
    "prev_build_id       TEXT, "
    "change_summary_json TEXT NOT NULL DEFAULT '{}', "
    # building|active|superseded|failed
    "status              TEXT NOT NULL, "
    "started_at          INTEGER NOT NULL, "
    "finished_at         INTEGER)",
)

#: DDL владельца версионного членства — `v44`. PK запрещает дубль узла в
#: одной сборке/сообществе; канонический `nodes.id` (после redirect
#: `entity_resolver`), не Telegram UID (§6).
COMMUNITY_MEMBERS_DDL_SQLITE: tuple[str, ...] = (
    f"CREATE TABLE IF NOT EXISTS {COMMUNITY_MEMBERS_TABLE} ("
    "chat_id       INTEGER NOT NULL, "
    "build_id      TEXT NOT NULL, "
    "community_id  TEXT NOT NULL, "
    "node_id       INTEGER NOT NULL, "
    "member_weight REAL NOT NULL DEFAULT 1.0, "
    "created_at    INTEGER NOT NULL, "
    "PRIMARY KEY (chat_id, build_id, community_id, node_id))",
)

#: Индексы владельца (§5.1): реестр сборок читается по
#: `(chat_id, status, started_at DESC)`, членство — по узлу и по сообществу.
COMMUNITY_INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_mca_community_builds_chat_status "
    f"ON {COMMUNITY_BUILDS_TABLE} (chat_id, status, started_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_mca_community_members_node "
    f"ON {COMMUNITY_MEMBERS_TABLE} (chat_id, build_id, node_id)",
    "CREATE INDEX IF NOT EXISTS idx_mca_community_members_community "
    f"ON {COMMUNITY_MEMBERS_TABLE} (chat_id, build_id, community_id)",
)

# ── закрытые строковые значения `mca_community_builds.status` (§6) ─────────
STATUS_BUILDING = "building"
STATUS_ACTIVE = "active"
STATUS_SUPERSEDED = "superseded"
STATUS_FAILED = "failed"

# ── веса и классы происхождения связи (§6, MEM-07.2) ───────────────────────
PROVENANCE_CONFIRMED = "confirmed"
PROVENANCE_TENTATIVE = "tentative"
PROVENANCE_LEGACY = "legacy"
PROVENANCE_COOCCURRENCE = "cooccurrence"

#: Точные веса контракта: `confirmed` 1.0 / `tentative` 0.5 / `legacy` 0.25 /
#: `cooccurrence` 0.1. Ни одно другое значение не допускается.
PROVENANCE_WEIGHTS: dict[str, float] = {
    PROVENANCE_CONFIRMED: 1.0,
    PROVENANCE_TENTATIVE: 0.5,
    PROVENANCE_LEGACY: 0.25,
    PROVENANCE_COOCCURRENCE: 0.1,
}

#: Источник связи: строка `edges` (оканчивается фактом/legacy) либо пара из
#: `mca_associations` (гипотеза совместности, только `cooccurrence`).
LINK_SOURCE_EDGE = "edge"
LINK_SOURCE_ASSOCIATION = "association"

#: Алгоритм и версия пишутся в `mca_community_builds` (§6): детерминированное
#: локальное движение по модульности на взвешенном неориентированном графе
#: (Leiden/Louvain-семейство допустимо источником MEM-07.2). Один уровень, без
#: агрегации: для сообществ чата этого достаточно, а детерминизм и стоимость
#: проверяемы. Порядок узлов — возрастание канонического `nodes.id`,
#: разрешение ничьих — меньший id сообщества; поэтому результат — функция
#: входа, а не порядка обхода словаря.
COMMUNITY_ALGORITHM = "weighted_modularity_local_moving"
COMMUNITY_ALGORITHM_VERSION = "1"
#: Потолок проходов локального движения (защита от немонотонных float-сумм).
COMMUNITY_MAX_PASSES = 12
#: Сообщество — это связная группа не менее двух узлов; одиночный узел без
#: связей не образует сообщества и в членство не попадает (иначе членство
#: состояло бы из синглтонов без единого основания).
COMMUNITY_MIN_SIZE = 2
#: Минимальная доля пересечения (от меньшего из двух составов), при которой
#: `community_id` предыдущей сборки переносится на новую: обычный малый drift
#: сохраняет id, а split/merge фиксируется в `change_summary_json` (§6).
COMMUNITY_REUSE_OVERLAP = 0.5
#: Доля внутреннего веса, начиная с которой сущность считается доминирующей
#: для подписи (MEM-07.4): иначе подпись нейтральная.
COMMUNITY_DOMINANT_SHARE = 0.5
#: Сколько доминирующих имён максимум попадает в подпись.
COMMUNITY_LABEL_MAX_NAMES = 3
#: Причины изменения состава в `change_summary_json` (§6: «фиксирует
#: split/merge, причины и mapping»).
REASON_SPLIT = "prev_community_spread_over_several_new"
REASON_MERGE = "new_community_overlaps_several_prev"
REASON_CREATED = "no_prev_overlap_at_or_above_threshold"
REASON_DROPPED = "no_new_overlap_at_or_above_threshold"
#: Нейтральная подпись и честное «неизвестно» (MEM-07.4).
NEUTRAL_LABEL_TEMPLATE = "Сообщество {ordinal}"
UNKNOWN_VALUE_TEXT = "Неизвестно"

# ── MEMORY-07 §14.2 (замороженный quality contract): PROVEN / WEAK ─────────
#: `PROVEN` ⇔ одновременно `size ≥ 3`, `S ≥ 1.0`, `S/T ≥ 0.5`, где
#: S = confirmed×1.0 + tentative×0.5, T = S + legacy×0.25 + cooccurrence×0.1
#: по связям ВНУТРИ сообщества. Всё остальное — `WEAK`. Порог не ослабляется
#: «под данные»: 74.2% корпуса — пары размера 2, и именно они отклонены
#: владельцем. Одно сообщество из 3 933 — честный размер доказанной части.
COMMUNITY_STATUS_PROVEN = mc.CommunityStatus.PROVEN.value
COMMUNITY_STATUS_WEAK = mc.CommunityStatus.WEAK.value
COMMUNITY_PROVEN_MIN_SIZE = 3
COMMUNITY_PROVEN_MIN_STRONG_WEIGHT = 1.0
COMMUNITY_PROVEN_MIN_STRONG_SHARE = 0.5
#: Допуск только на двоичное представление 0.25/0.5-долей, не на «почти»:
#: без него сумма 0.25+0.25 могла бы оказаться 0.49999999999999994.
_EPS = 1e-9

#: Потолок длины сохранённого текста ошибки сборки (диагностика, без текстов
#: чата).
_ERROR_MAX_CHARS = 200

#: Размеры/доли, попадающие в `params_json` сборки (наблюдаемость версии
#: расчёта, MEM-07.2 «хранить результат/версию расчёта»).
BUILD_PARAMS: dict[str, Any] = {
    "weights": dict(PROVENANCE_WEIGHTS),
    "min_community_size": COMMUNITY_MIN_SIZE,
    "reuse_overlap": COMMUNITY_REUSE_OVERLAP,
    "max_passes": COMMUNITY_MAX_PASSES,
    "dominant_share": COMMUNITY_DOMINANT_SHARE,
}

# ── связи графа (внутреннее представление) ─────────────────────────────────


@dataclasses.dataclass(frozen=True)
class EvidenceLink:
    """Одна взвешенная связь между двумя каноническими `nodes.id`.

    `provenance` — бакет веса §6; `source` — `edge` либо `association`.
    Ко–встречаемость никогда не становится `confirmed` (§6, MEM-07.6).
    """

    node_a: int
    node_b: int
    weight: float
    provenance: str
    source: str
    last_activity: int | None = None

    def as_dict(self) -> dict:
        return {
            "node_a": int(self.node_a), "node_b": int(self.node_b),
            "weight": float(self.weight), "provenance": self.provenance,
            "source": self.source, "last_activity": self.last_activity,
        }


@dataclasses.dataclass(frozen=True)
class CommunityStats:
    """Метрики сообщества из настоящих данных; неизвестное — `Неизвестно`."""

    node_count: int
    confirmed_links: int
    tentative_links: int
    legacy_links: int
    cooccurrence_links: int
    density: float | None
    last_activity: int | None

    @property
    def last_activity_text(self) -> str:
        return ("Неизвестно" if self.last_activity is None
                else str(int(self.last_activity)))

    @property
    def strong_weight(self) -> float:
        """S = confirmed×1.0 + tentative×0.5 (§14.2) — факт-обоснованный вес."""
        return round(float(self.confirmed_links) *
                     PROVENANCE_WEIGHTS[PROVENANCE_CONFIRMED]
                     + float(self.tentative_links) *
                     PROVENANCE_WEIGHTS[PROVENANCE_TENTATIVE], 6)

    @property
    def total_weight(self) -> float:
        """T = S + legacy×0.25 + cooccurrence×0.1 (§14.2) — весь внутренний вес."""
        return round(
            self.strong_weight
            + float(self.legacy_links) * PROVENANCE_WEIGHTS[PROVENANCE_LEGACY]
            + float(self.cooccurrence_links)
            * PROVENANCE_WEIGHTS[PROVENANCE_COOCCURRENCE], 6)

    @property
    def strong_share(self) -> float | None:
        """S/T — доля внутреннего веса, подтверждённая фактами; None без веса."""
        total = self.total_weight
        if total <= 0:
            return None
        return round(self.strong_weight / total, 6)

    def as_dict(self) -> dict:
        return {
            "node_count": int(self.node_count),
            "confirmed_links": int(self.confirmed_links),
            "tentative_links": int(self.tentative_links),
            "legacy_links": int(self.legacy_links),
            "cooccurrence_links": int(self.cooccurrence_links),
            "density": self.density,
            "last_activity": self.last_activity,
            "last_activity_text": self.last_activity_text,
        }


@dataclasses.dataclass(frozen=True)
class CommunityLabel:
    """Подпись сообщества и её основание (MEM-07.4, без LLM)."""

    community_id: str
    label: str
    basis: str
    dominant_names: tuple[str, ...]

    @property
    def is_neutral(self) -> bool:
        """Нейтральная подпись (`Сообщество N`) — диагностика, НЕ категория.

        §14.3: такая подпись не выводится ни в поиск, ни в визуальный граф;
        потребитель обязан опираться на этот признак, а не на текст шаблона.
        """
        return not self.dominant_names

    def as_dict(self) -> dict:
        return {
            "community_id": self.community_id, "label": self.label,
            "basis": self.basis,
            "dominant_names": list(self.dominant_names),
        }


@dataclasses.dataclass(frozen=True)
class BuiltCommunity:
    """Сообщество одной сборки: члены, веса, метрики, подпись."""

    community_id: str
    members: tuple[int, ...]
    member_weights: Mapping[int, float]
    stats: CommunityStats
    label: CommunityLabel

    def as_dict(self) -> dict:
        return {
            "community_id": self.community_id,
            "members": list(self.members),
            "member_weights": {int(k): float(v)
                               for k, v in sorted(self.member_weights.items())},
            "stats": self.stats.as_dict(),
            "label": self.label.as_dict(),
        }


@dataclasses.dataclass(frozen=True)
class BuildResult:
    """Результат одной сборки (в т.ч. честный `failed`)."""

    build_id: str
    chat_id: int
    status: str
    graph_revision: str
    node_count: int
    edge_count: int
    prev_build_id: str | None
    communities: tuple[BuiltCommunity, ...]
    change_summary: Mapping[str, Any]
    provenance_counts: Mapping[str, int]
    error: str | None = None
    started_at: int = 0
    finished_at: int | None = None

    @property
    def member_count(self) -> int:
        return sum(len(c.members) for c in self.communities)

    def as_dict(self) -> dict:
        return {
            "build_id": self.build_id, "chat_id": int(self.chat_id),
            "status": self.status, "graph_revision": self.graph_revision,
            "node_count": int(self.node_count),
            "edge_count": int(self.edge_count),
            "prev_build_id": self.prev_build_id,
            "communities": [c.as_dict() for c in self.communities],
            "change_summary": dict(self.change_summary),
            "provenance_counts": dict(self.provenance_counts),
            "error": self.error,
            "started_at": int(self.started_at),
            "finished_at": self.finished_at,
            "algorithm": COMMUNITY_ALGORITHM,
            "algorithm_version": COMMUNITY_ALGORITHM_VERSION,
        }


# ── веса и классы происхождения (§6, MEM-07.2) ─────────────────────────────


def fact_provenance(fact_row: Mapping[str, Any] | None) -> str:
    """Класс факта → бакет веса §6 через `classify_fact_provenance`.

    `confident` → `confirmed`, `tentative` → `tentative`, всё остальное
    (`legacy_unverified`) → `legacy`. Второй классификации нет.
    """
    if fact_row is None:
        return PROVENANCE_LEGACY
    cls = provenance.classify_fact_provenance(dict(fact_row))
    if cls == provenance.EDGE_CONFIDENT:
        return PROVENANCE_CONFIRMED
    if cls == provenance.EDGE_TENTATIVE:
        return PROVENANCE_TENTATIVE
    return PROVENANCE_LEGACY


def link_weight(provenance_class: str) -> float:
    """Точный вес класса; неизвестный класс — ошибка, а не «примерно 1.0»."""
    try:
        return PROVENANCE_WEIGHTS[provenance_class]
    except KeyError:                                 # pragma: no cover — защита
        raise ValueError(f"unknown community link provenance: "
                         f"{provenance_class!r}") from None


def association_provenance() -> str:
    """Класс пары `mca_associations`: всегда `cooccurrence` (§6, MEM-07.6)."""
    return PROVENANCE_COOCCURRENCE


def _emit(event_name: str, *, outcome: str = "success", **fields: Any) -> None:
    """Наблюдаемость без текстов чата; телеметрия не рвёт сборку."""
    try:
        mca_events.emit_mca_event(event_name, outcome=outcome,
                                  component="memory_communities", **fields)
    except Exception:                                # pragma: no cover — fail-open
        logger.debug("[memory_communities] event failed | %s", event_name,
                     exc_info=True)


# ── чтение снимка (только чтение) ──────────────────────────────────────────


async def _fetchall(db, sql: str, params=()) -> list[Any]:
    cursor = await db.db.execute(sql, tuple(params))
    return list(await cursor.fetchall())


async def _read_nodes(db, chat_id: int) -> list[dict]:
    rows = await _fetchall(
        db,
        "SELECT id, entity_name, entity_type FROM nodes WHERE chat_id = ? "
        "ORDER BY id", (int(chat_id),))
    return [{"id": int(r["id"]), "entity_name": str(r["entity_name"] or ""),
             "entity_type": str(r["entity_type"] or "")} for r in rows]


async def _read_active_canonical_rows(db, chat_id: int) -> dict[int, int]:
    """Активные redirect-строки `mca_entity_canonical` (member → canonical).

    Доступна только таблица `entity_resolver` (второго словаря идентичности
    нет); разрешение имён делает сам резолвер (`_resolve_canonical_ids`).
    """
    try:
        rows = await _fetchall(
            db,
            f"SELECT member_node_id, canonical_node_id "
            f"FROM {entity_resolver.ENTITY_CANONICAL_TABLE} "
            "WHERE chat_id = ? AND status = ?",
            (int(chat_id), entity_resolver.STATUS_ACTIVE))
    except Exception:                                # pragma: no cover — до v43
        return {}
    mapping: dict[int, int] = {}
    for row in rows:
        member = int(row["member_node_id"])
        canonical = int(row["canonical_node_id"])
        if member != canonical:
            mapping[member] = canonical
    return mapping


async def _resolve_canonical_ids(db, chat_id: int, nodes: list[dict],
                                 canonical_rows: Mapping[int, int]
                                 ) -> tuple[dict[int, int], tuple[int, ...]]:
    """Канонический `nodes.id` для member-узлов — через `entity_resolver`.

    Вызывается только для узлов, у которых есть активная redirect-строка
    (identity уже установлена доказательством, §1.2.1/§1.4): полного
    `resolve_entity` по каждому узлу чата сборка не делает. Резолвер
    read-only (ID-1) и сам схлопывает цепочку (§1.4.2); `rejected`/
    `ambiguous` не выдаются за канонический id — узел остаётся собой, факт
    виден в `degraded` счётчике.
    """
    by_id = {int(n["id"]): n for n in nodes}
    canonical: dict[int, int] = {}
    unresolved: list[int] = []
    for member_id in sorted(canonical_rows):
        node = by_id.get(int(member_id))
        if node is None:
            continue
        try:
            resolution = await entity_resolver.resolve_entity(
                db,
                scope={"chat_id": int(chat_id),
                       "entity_type": node["entity_type"]},
                mention=node["entity_name"])
        except Exception:                            # pragma: no cover — защита
            logger.debug("[memory_communities] resolve failed | chat=%s node=%s",
                         chat_id, member_id, exc_info=True)
            unresolved.append(int(member_id))
            continue
        ref = resolution.canonical
        if (resolution.status == mc.EntityResolutionStatus.RESOLVED
                and ref is not None and int(ref.node_id) in by_id
                and int(ref.node_id) != int(member_id)):
            canonical[int(member_id)] = int(ref.node_id)
        else:
            unresolved.append(int(member_id))
    return canonical, tuple(unresolved)


async def _read_edges(db, chat_id: int) -> list[dict]:
    rows = await _fetchall(
        db,
        "SELECT id, source_id, target_id, fact_id, last_updated FROM edges "
        "WHERE chat_id = ? ORDER BY id", (int(chat_id),))
    return [{"id": int(r["id"]), "source_id": int(r["source_id"]),
             "target_id": int(r["target_id"]),
             "fact_id": (None if r["fact_id"] is None else int(r["fact_id"])),
             "last_updated": r["last_updated"]} for r in rows]


async def _read_facts(db, chat_id: int) -> dict[int, dict]:
    """Только колонки, которые читает `classify_fact_provenance`."""
    rows = await _fetchall(
        db,
        "SELECT id, subject_ref_id, speaker_author_id FROM graph_facts "
        "WHERE chat_id = ? ORDER BY id", (int(chat_id),))
    return {int(r["id"]): {"id": int(r["id"]),
                           "subject_ref_id": r["subject_ref_id"],
                           "speaker_author_id": r["speaker_author_id"]}
            for r in rows}


async def _read_association_rows(db, chat_id: int) -> list[dict]:
    """Пары `mca_associations` (candidate/accepted) с участниками эпизодов.

    Стороны ассоциации — `episode_id`, поэтому узлы получаются из
    `participants_json` эпизодов. Один JOIN, без второго хранилища и без
    скана всех эпизодов чата.
    """
    try:
        rows = await _fetchall(
            db,
            "SELECT a.association_id AS association_id, "
            "a.a_event_id AS a_event_id, a.b_event_id AS b_event_id, "
            "ea.participants_json AS a_participants, "
            "eb.participants_json AS b_participants "
            "FROM mca_associations a "
            "LEFT JOIN mca_episodes ea ON ea.episode_id = a.a_event_id "
            "AND ea.chat_id = a.chat_id "
            "LEFT JOIN mca_episodes eb ON eb.episode_id = a.b_event_id "
            "AND eb.chat_id = a.chat_id "
            "WHERE a.chat_id = ? AND a.status IN ('candidate','accepted') "
            "ORDER BY a.association_id", (int(chat_id),))
    except Exception:                                # pragma: no cover — до v30
        logger.debug("[memory_communities] associations unavailable | chat=%s",
                     chat_id, exc_info=True)
        return []
    return [{"association_id": str(r["association_id"]),
             "a_participants": _json_list(r["a_participants"]),
             "b_participants": _json_list(r["b_participants"])}
            for r in rows]


def _json_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):                  # pragma: no cover — дефект
        return []
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


async def _participant_node_ids(db, chat_id: int, participants: Sequence[str],
                                cache: dict[str, int | None],
                                node_ids: set[int]) -> tuple[int, ...]:
    """Участники эпизода → канонические `nodes.id` через `entity_resolver`."""
    resolved: list[int] = []
    for raw in participants:
        text = str(raw or "").strip()
        if not text:
            continue
        if text not in cache:
            stable = None
            if text.isdigit():
                stable = {"kind": entity_resolver.STABLE_KIND_TG_USER,
                          "value": int(text)}
            node_id: int | None = None
            try:
                resolution = await entity_resolver.resolve_entity(
                    db, scope={"chat_id": int(chat_id),
                               "entity_type": "user"},
                    mention=text, stable_identity=stable)
            except Exception:                        # pragma: no cover — защита
                resolution = None
            if resolution is not None:
                ref = resolution.canonical
                if (resolution.status == mc.EntityResolutionStatus.RESOLVED
                        and ref is not None and int(ref.node_id) in node_ids):
                    node_id = int(ref.node_id)
            cache[text] = node_id
        node_id = cache[text]
        if node_id is not None and node_id not in resolved:
            resolved.append(node_id)
    return tuple(sorted(resolved))


# ── построение связей и весов (§6) ─────────────────────────────────────────


async def _collect_links(db, chat_id: int, *, nodes: list[dict],
                         canonical: Mapping[int, int],
                         facts: Mapping[int, dict],
                         associations: Sequence[Mapping[str, Any]]
                         ) -> tuple[list[EvidenceLink], dict[str, int], int]:
    """Взвешенные связи чата: `edges` (факт/legacy) + `mca_associations`.

    Возвращает `(связи, счётчики провенанса, число отброшенных связей)`.
    Связи вне chat scope (узел не из этого чата), самопетли и пары, схлопнутые
    в один канонический узел, в граф не попадают — это видимая деградация, а
    не «примерно то же самое».
    """
    node_ids = {int(n["id"]) for n in nodes}

    def _canonical(node_id: int) -> int:
        seen: set[int] = set()
        current = int(node_id)
        while current in canonical and current not in seen:
            seen.add(current)
            current = int(canonical[current])
        return current

    links: list[EvidenceLink] = []
    counts = {key: 0 for key in PROVENANCE_WEIGHTS}
    dropped = 0

    for edge in await _read_edges(db, chat_id):
        source = _canonical(edge["source_id"])
        target = _canonical(edge["target_id"])
        if (source not in node_ids or target not in node_ids
                or source == target):
            dropped += 1
            continue
        fact = facts.get(edge["fact_id"]) if edge["fact_id"] is not None else None
        provenance_class = fact_provenance(fact)
        weight = link_weight(provenance_class)
        links.append(EvidenceLink(
            node_a=min(source, target), node_b=max(source, target),
            weight=weight, provenance=provenance_class,
            source=LINK_SOURCE_EDGE,
            last_activity=parse_edge_timestamp(edge["last_updated"])))
        counts[provenance_class] += 1

    participant_cache: dict[str, int | None] = {}
    for row in associations:
        participants_a = set(await _participant_node_ids(
            db, chat_id, row["a_participants"], participant_cache, node_ids))
        participants_b = set(await _participant_node_ids(
            db, chat_id, row["b_participants"], participant_cache, node_ids))
        for node_a in sorted(participants_a):
            for node_b in sorted(participants_b):
                if node_a == node_b:
                    continue
                provenance_class = association_provenance()
                links.append(EvidenceLink(
                    node_a=min(node_a, node_b), node_b=max(node_a, node_b),
                    weight=link_weight(provenance_class),
                    provenance=provenance_class,
                    source=LINK_SOURCE_ASSOCIATION, last_activity=None))
                counts[provenance_class] += 1

    return links, counts, dropped


def _adjacency(node_ids: Sequence[int], links: Sequence[EvidenceLink]
               ) -> dict[int, dict[int, float]]:
    """Симметричная взвешенная смежность: сумма весов всех связей пары."""
    adjacency: dict[int, dict[int, float]] = {int(n): {} for n in node_ids}
    for link in links:
        if link.node_a == link.node_b:
            continue
        row = adjacency.setdefault(link.node_a, {})
        row[link.node_b] = round(row.get(link.node_b, 0.0) + link.weight, 6)
        row = adjacency.setdefault(link.node_b, {})
        row[link.node_a] = round(row.get(link.node_a, 0.0) + link.weight, 6)
    return adjacency


# ── детерминированное разбиение (§6, MEM-07.2) ─────────────────────────────


def detect_communities(node_ids: Sequence[int],
                       adjacency: Mapping[int, Mapping[int, float]], *,
                       max_passes: int = COMMUNITY_MAX_PASSES
                       ) -> tuple[frozenset[int], ...]:
    """Детерминированное разбиение на сообщества по взвешенной модульности.

    Один уровень локального движения (семейство Louvain, допустимое
    MEM-07.2): узлы обходятся по возрастанию `nodes.id`, кандидат — метка с
    максимальным выигрышем, ничья не двигает узел (строгое улучшение на
    `1e-12`), поэтому разбиение — функция входа. Возвращает группы, включая
    синглтоны (фильтр размера — у вызывающего), отсортированные по
    минимальному id.
    """
    order = sorted(int(n) for n in node_ids)
    community = {n: n for n in order}
    degree = {n: 0.0 for n in order}
    total_weight = 0.0
    for node in order:
        neighbours = adjacency.get(node) or {}
        for other in sorted(int(o) for o in neighbours):
            weight = float(neighbours[other])
            if weight <= 0:
                continue
            degree[node] += weight
            if node < other:
                total_weight += weight
    if total_weight <= 0:
        return tuple(frozenset((n,)) for n in order)

    two_m = 2.0 * total_weight
    totals: dict[int, float] = {}
    for node in order:
        label = community[node]
        totals[label] = totals.get(label, 0.0) + degree[node]

    epsilon = 1e-12
    for _ in range(max(0, int(max_passes))):
        moved = 0
        for node in order:
            current = community[node]
            k_node = degree[node]
            weights_to: dict[int, float] = {}
            for other, weight in sorted(
                    (adjacency.get(node) or {}).items()):
                label = community[int(other)]
                weights_to[label] = weights_to.get(label, 0.0) + float(weight)
            totals[current] = totals.get(current, 0.0) - k_node
            best_label = current
            best_gain = (weights_to.get(current, 0.0)
                         - totals.get(current, 0.0) * k_node / two_m)
            for label in sorted(weights_to):
                if label == current:
                    continue
                gain = (weights_to[label]
                        - totals.get(label, 0.0) * k_node / two_m)
                if gain > best_gain + epsilon:
                    best_label, best_gain = label, gain
            if best_label != current:
                community[node] = best_label
                totals[best_label] = totals.get(best_label, 0.0) + k_node
                moved += 1
            else:
                totals[current] = totals.get(current, 0.0) + k_node
        if moved == 0:
            break

    groups: dict[int, set[int]] = {}
    for node in order:
        groups.setdefault(community[node], set()).add(node)
    return tuple(sorted((frozenset(members) for members in groups.values()),
                        key=lambda members: (min(members), len(members))))


# ── идентификаторы и mapping split/merge (§6, MEM-07.5) ────────────────────


def _new_community_id(members: Sequence[int], used: set[str]) -> str:
    """Новый детерминированный id: `c<минимальный nodes.id>` (без коллизий)."""
    base = f"c{min(int(m) for m in members)}"
    candidate = base
    suffix = 1
    while candidate in used:
        suffix += 1
        candidate = f"{base}-{suffix}"
    used.add(candidate)
    return candidate


def map_community_ids(new_sets: Sequence[frozenset[int]],
                      prev_members: Mapping[str, set[int]]
                      ) -> tuple[list[str], dict[str, Any]]:
    """Перенос `community_id` предыдущей сборки на новую + `change_summary`.

    Правило (§6): при неизменном membership id сохраняются; при малом drift
    id переносится сопоставлением (доля пересечения от меньшего состава ≥
    `COMMUNITY_REUSE_OVERLAP`); при split/merge старые id не переписываются —
    один из новых составов получает сопоставленный id, остальные новые, а
    `change_summary_json` фиксирует `split`/`merge`/`created`/`dropped` и
    mapping. Сопоставление жадно и детерминировано: больший overlap, затем
    меньший предыдущий id, затем меньший индекс.
    """
    overlaps: list[tuple[int, str, int]] = []
    for index, members in enumerate(new_sets):
        for prev_id in sorted(prev_members):
            common = len(members & prev_members[prev_id])
            if common:
                overlaps.append((index, prev_id, common))
    overlaps.sort(key=lambda item: (-item[2], item[1], item[0]))

    assigned: dict[int, str] = {}
    used_prev: set[str] = set()
    for index, prev_id, common in overlaps:
        if index in assigned or prev_id in used_prev:
            continue
        smaller = min(len(new_sets[index]), len(prev_members[prev_id]))
        if smaller == 0 or common / smaller < COMMUNITY_REUSE_OVERLAP:
            continue
        assigned[index] = prev_id
        used_prev.add(prev_id)

    used_ids: set[str] = set(prev_members)
    ids: list[str] = []
    for index, members in enumerate(new_sets):
        if index in assigned:
            ids.append(assigned[index])
            continue
        ids.append(_new_community_id(members, used_ids))

    created = sorted(ids[index] for index in range(len(new_sets))
                     if index not in assigned)
    dropped = sorted(set(prev_members) - set(ids))

    parts: dict[str, list[str]] = {}
    for index, members in enumerate(new_sets):
        for prev_id in sorted(prev_members):
            common = len(members & prev_members[prev_id])
            if not common or not members:
                continue
            if common / len(members) >= COMMUNITY_REUSE_OVERLAP:
                parts.setdefault(prev_id, []).append(ids[index])
    split = [{"prev_community_id": prev_id,
              "parts": sorted(part_ids),
              "reason": REASON_SPLIT}
             for prev_id, part_ids in sorted(parts.items())
             if len(part_ids) > 1]

    merged: list[dict[str, Any]] = []
    for index, members in enumerate(new_sets):
        sources = sorted(
            prev_id for prev_id in prev_members
            if members and len(members & prev_members[prev_id]) / len(members)
            >= COMMUNITY_REUSE_OVERLAP)
        if len(sources) > 1:
            merged.append({"community_id": ids[index],
                           "prev_community_ids": sources,
                           "reason": REASON_MERGE})

    summary: dict[str, Any] = {
        "reused": len(assigned),
        "created": created,
        "dropped": dropped,
        "mapping": {ids[index]: prev_id
                    for index, prev_id in sorted(assigned.items(),
                                                 key=lambda kv: ids[kv[0]])},
        "split": split,
        "merge": sorted(merged, key=lambda item: item["community_id"]),
        "reasons": {
            "created": REASON_CREATED,
            "dropped": REASON_DROPPED,
            "split": REASON_SPLIT,
            "merge": REASON_MERGE,
        },
    }
    return ids, summary


# ── метрики и подписи (§6, MEM-07.4) ───────────────────────────────────────


def community_stats(members: Sequence[int],
                    internal_links: Sequence[EvidenceLink]) -> CommunityStats:
    """Метрики сообщества по настоящим связям; неизвестное — `Неизвестно`."""
    member_set = {int(m) for m in members}
    confirmed = tentative = legacy = cooccurrence = 0
    pairs: dict[tuple[int, int], float] = {}
    last_activity: int | None = None
    for link in internal_links:
        if link.node_a not in member_set or link.node_b not in member_set:
            continue
        if link.provenance == PROVENANCE_CONFIRMED:
            confirmed += 1
        elif link.provenance == PROVENANCE_TENTATIVE:
            tentative += 1
        elif link.provenance == PROVENANCE_LEGACY:
            legacy += 1
        else:
            cooccurrence += 1
        key = (link.node_a, link.node_b)
        pairs[key] = round(pairs.get(key, 0.0) + link.weight, 6)
        if link.last_activity is not None:
            moment = int(link.last_activity)
            last_activity = moment if last_activity is None \
                else max(last_activity, moment)
    size = len(member_set)
    density: float | None = None
    if size >= 2:
        density = round(len(pairs) / (size * (size - 1) / 2), 6)
    return CommunityStats(
        node_count=size, confirmed_links=confirmed, tentative_links=tentative,
        legacy_links=legacy, cooccurrence_links=cooccurrence,
        density=density, last_activity=last_activity)


def community_label(community_id: str, *, ordinal: int,
                    members: Sequence[int], internal_links: Sequence[EvidenceLink],
                    weights: Mapping[int, float],
                    names: Mapping[int, str],
                    stats: CommunityStats) -> CommunityLabel:
    """Подпись и основание (MEM-07.4): доминирующие сущности с источниками.

    Доминирует сущность, у которой есть связь с источником (не только
    `cooccurrence`) и внутренний вес ≥ `COMMUNITY_DOMINANT_SHARE` от общего
    внутреннего веса сообщества; иначе подпись нейтральная
    «Сообщество N». LLM не участвует.
    """
    total = round(sum(float(weights.get(int(m), 0.0)) for m in members), 6)
    sourced: set[int] = set()
    for link in internal_links:
        # «С источниками» (MEM-07.4): только факт-обоснованные классы. Legacy
        # без происхождения и совпадение основанием подписи не являются.
        if link.provenance not in (PROVENANCE_CONFIRMED, PROVENANCE_TENTATIVE):
            continue
        sourced.add(link.node_a)
        sourced.add(link.node_b)

    dominant: list[tuple[float, int, str]] = []
    if total > 0:
        for node_id in sorted(weights, key=lambda n: (-float(weights[n]),
                                                      int(n))):
            if int(node_id) not in sourced:
                continue
            weight = float(weights[node_id])
            if weight <= 0:
                continue
            if weight / total + 1e-12 < COMMUNITY_DOMINANT_SHARE:
                continue
            name = str(names.get(int(node_id)) or "").strip()
            if not name:
                continue
            dominant.append((weight, int(node_id), name))
            if len(dominant) >= COMMUNITY_LABEL_MAX_NAMES:
                break

    if dominant:
        label = "Сообщество: " + ", ".join(name for _, _, name in dominant)
    else:
        label = NEUTRAL_LABEL_TEMPLATE.format(ordinal=int(ordinal))

    basis = _label_basis(stats)
    return CommunityLabel(community_id=community_id, label=label, basis=basis,
                          dominant_names=tuple(name for _, _, name
                                               in dominant))


def _label_basis(stats: CommunityStats) -> str:
    """«Как сформировано» из настоящих метрик, без догадок."""
    density = (UNKNOWN_VALUE_TEXT if stats.density is None
               else f"{stats.density:.3f}")
    return (
        f"сформировано по реальным связям чата: узлов {stats.node_count}, "
        f"связей подтверждённых {stats.confirmed_links}, сомнительных "
        f"{stats.tentative_links}, без происхождения {stats.legacy_links}, "
        f"совпадений {stats.cooccurrence_links}; плотность {density}; "
        f"последняя активность {stats.last_activity_text}")


def classify_community_status(*, size: int, strong_weight: float,
                              total_weight: float) -> str:
    """PROVEN/WEAK по порогам §14.2 (единственное место правила).

    `PROVEN` ⇔ `size ≥ 3` И `S ≥ 1.0` И `S/T ≥ 0.5`; иначе `WEAK`.
    Границы входят в PROVEN (`≥`, не `>`); допуск — только на двоичную
    запись долей (`_EPS`), не на «почти порог».
    """
    if int(size) < COMMUNITY_PROVEN_MIN_SIZE:
        return COMMUNITY_STATUS_WEAK
    if float(strong_weight) + _EPS < COMMUNITY_PROVEN_MIN_STRONG_WEIGHT:
        return COMMUNITY_STATUS_WEAK
    if float(total_weight) <= 0:
        return COMMUNITY_STATUS_WEAK
    share = float(strong_weight) / float(total_weight)
    if share + _EPS < COMMUNITY_PROVEN_MIN_STRONG_SHARE:
        return COMMUNITY_STATUS_WEAK
    return COMMUNITY_STATUS_PROVEN


def community_status(stats: CommunityStats) -> str:
    """Статус сообщества по его настоящим метрикам (§14.2)."""
    return classify_community_status(
        size=stats.node_count, strong_weight=stats.strong_weight,
        total_weight=stats.total_weight)


def community_quality(community: BuiltCommunity) -> dict:
    """Компактная запись качества сообщества для `change_summary_json`.

    Хранится БЕЗ DDL (§5.1): proven-сообществ на практике единицы, поэтому
    список остаётся маленьким. `label` попадает только не-нейтральная —
    нейтральная подпись остаётся диагностикой сборки (§14.3)."""
    stats = community.stats
    label = community.label
    return {
        "community_id": community.community_id,
        "status": community_status(stats),
        "size": int(stats.node_count),
        "strong_share": stats.strong_share,
        "density": stats.density,
        "basis": label.basis,
        "label": (None if label.is_neutral else label.label),
    }


# ── жизненный цикл сборки (§6) ─────────────────────────────────────────────


async def _previous_active_build(db, chat_id: int) -> str | None:
    rows = await _fetchall(
        db,
        f"SELECT build_id FROM {COMMUNITY_BUILDS_TABLE} "
        "WHERE chat_id = ? AND status = ? "
        "ORDER BY started_at DESC, build_id DESC LIMIT 1",
        (int(chat_id), STATUS_ACTIVE))
    return str(rows[0]["build_id"]) if rows else None


async def _read_build_members(db, chat_id: int, build_id: str
                              ) -> dict[str, set[int]]:
    rows = await _fetchall(
        db,
        f"SELECT community_id, node_id FROM {COMMUNITY_MEMBERS_TABLE} "
        "WHERE chat_id = ? AND build_id = ?", (int(chat_id), str(build_id)))
    members: dict[str, set[int]] = {}
    for row in rows:
        members.setdefault(str(row["community_id"]), set()).add(int(row["node_id"]))
    return members


async def _create_build_row(db, *, build_id: str, chat_id: int,
                            graph_revision: str, node_count: int,
                            edge_count: int, prev_build_id: str | None,
                            started_at: int) -> None:
    """Строка `building` создаётся ДО расчёта: падение оставляет след `failed`."""
    async def _body(conn):
        await conn.execute(
            f"INSERT INTO {COMMUNITY_BUILDS_TABLE} (build_id, chat_id, "
            "algorithm, algorithm_version, params_json, graph_revision, "
            "node_count, edge_count, prev_build_id, change_summary_json, "
            "status, started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, NULL)",
            (str(build_id), int(chat_id), COMMUNITY_ALGORITHM,
             COMMUNITY_ALGORITHM_VERSION,
             json.dumps(BUILD_PARAMS, ensure_ascii=False, sort_keys=True),
             str(graph_revision), int(node_count), int(edge_count),
             (None if prev_build_id is None else str(prev_build_id)),
             STATUS_BUILDING, int(started_at)))

    await db.write_transaction(_body, op_name="community_build_create",
                               chat_id=int(chat_id))


async def _assert_publication_complete(conn, *, chat_id: int, build_id: str,
                                       expected_members: Sequence[int]
                                       ) -> None:
    """Инвариант публикации: ровно полный набор членства, только свои узлы.

    Нарушение → исключение внутри транзакции публикации: частичная запись
    откатывается, сборка помечается `failed`, предыдущий `active` остаётся
    нетронутым (§6).
    """
    expected = sorted(int(n) for n in expected_members)
    cursor = await conn.execute(
        f"SELECT COUNT(*) FROM {COMMUNITY_MEMBERS_TABLE} "
        "WHERE chat_id = ? AND build_id = ?", (int(chat_id), str(build_id)))
    row = await cursor.fetchone()
    published_count = int(row[0]) if row is not None else 0
    if published_count != len(expected):
        raise RuntimeError("community_members_incomplete")
    cursor = await conn.execute(
        f"SELECT DISTINCT node_id FROM {COMMUNITY_MEMBERS_TABLE} "
        "WHERE chat_id = ? AND build_id = ?", (int(chat_id), str(build_id)))
    published = sorted(int(r[0]) for r in await cursor.fetchall())
    if published != expected:
        raise RuntimeError("community_members_mismatch")


async def _publish_build(db, *, build_id: str, chat_id: int,
                         communities: Sequence[BuiltCommunity],
                         change_summary: Mapping[str, Any],
                         node_count: int, edge_count: int,
                         finished_at: int) -> None:
    """Атомарная публикация: члены + supersede предыдущего + active новой.

    Всё в ОДНОЙ транзакции (§6): либо полный набор членства и ровно один
    `active` для чата, либо ничего (откат и `failed`).
    """
    member_weights: list[tuple[str, int, float]] = []
    for community in communities:
        for node_id in community.members:
            member_weights.append(
                (community.community_id, int(node_id),
                 float(community.member_weights.get(int(node_id), 1.0))))
    expected = [node_id for _, node_id, _ in member_weights]
    summary_json = json.dumps(dict(change_summary), ensure_ascii=False,
                              sort_keys=True)

    async def _body(conn):
        for community_id, node_id, weight in member_weights:
            await conn.execute(
                f"INSERT INTO {COMMUNITY_MEMBERS_TABLE} (chat_id, build_id, "
                "community_id, node_id, member_weight, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (int(chat_id), str(build_id), str(community_id), int(node_id),
                 float(weight), int(finished_at)))
        await _assert_publication_complete(
            conn, chat_id=int(chat_id), build_id=str(build_id),
            expected_members=expected)

        # Предыдущий active → superseded ТОЛЬКО здесь, вместе с полной
        # публикацией новой сборки. Failed-строка предыдущую не вытесняет.
        await conn.execute(
            f"UPDATE {COMMUNITY_BUILDS_TABLE} "
            "SET status = ?, finished_at = COALESCE(finished_at, ?) "
            "WHERE chat_id = ? AND status = ? AND build_id <> ?",
            (STATUS_SUPERSEDED, int(finished_at), int(chat_id), STATUS_ACTIVE,
             str(build_id)))
        cursor = await conn.execute(
            f"UPDATE {COMMUNITY_BUILDS_TABLE} "
            "SET status = ?, finished_at = ?, change_summary_json = ?, "
            "node_count = ?, edge_count = ? "
            "WHERE chat_id = ? AND build_id = ? AND status = ?",
            (STATUS_ACTIVE, int(finished_at), summary_json, int(node_count),
             int(edge_count), int(chat_id), str(build_id), STATUS_BUILDING))
        if int(cursor.rowcount or 0) != 1:
            raise RuntimeError("community_build_not_building")
        cursor = await conn.execute(
            f"SELECT COUNT(*) FROM {COMMUNITY_BUILDS_TABLE} "
            "WHERE chat_id = ? AND status = ?",
            (int(chat_id), STATUS_ACTIVE))
        row = await cursor.fetchone()
        if int(row[0] if row is not None else 0) != 1:
            raise RuntimeError("community_active_build_invariant")

    await db.write_transaction(_body, op_name="community_build_publish",
                               chat_id=int(chat_id))


async def _mark_build_failed(db, *, chat_id: int, build_id: str,
                             error: str, finished_at: int) -> None:
    """`building → failed`: частичное членство удаляется, `active` не тронут."""
    summary_json = json.dumps({"failed": True,
                               "reason": error[:_ERROR_MAX_CHARS]},
                              ensure_ascii=False, sort_keys=True)

    async def _body(conn):
        await conn.execute(
            f"DELETE FROM {COMMUNITY_MEMBERS_TABLE} "
            "WHERE chat_id = ? AND build_id = ?", (int(chat_id), str(build_id)))
        await conn.execute(
            f"UPDATE {COMMUNITY_BUILDS_TABLE} "
            "SET status = ?, finished_at = ?, change_summary_json = ? "
            "WHERE chat_id = ? AND build_id = ? AND status = ?",
            (STATUS_FAILED, int(finished_at), summary_json, int(chat_id),
             str(build_id), STATUS_BUILDING))

    try:
        await db.write_transaction(_body, op_name="community_build_fail",
                                   chat_id=int(chat_id))
    except Exception:                                # pragma: no cover — защита
        logger.warning("[memory_communities] failed to mark build failed | "
                       "chat=%s build=%s", chat_id, build_id, exc_info=True)


def _build_communities(*, node_ids: Sequence[int], links: Sequence[EvidenceLink],
                       names: Mapping[int, str]) -> tuple[BuiltCommunity, ...]:
    """Разбиение + веса + метрики + нейтральные подписи (детерминированно)."""
    adjacency = _adjacency(node_ids, links)
    groups = [members for members in detect_communities(node_ids, adjacency)
              if len(members) >= COMMUNITY_MIN_SIZE]
    communities: list[BuiltCommunity] = []
    for index, members in enumerate(groups, start=1):
        member_ids = tuple(sorted(int(m) for m in members))
        member_set = set(member_ids)
        internal = [link for link in links
                    if link.node_a in member_set and link.node_b in member_set]
        weights: dict[int, float] = {}
        for link in internal:
            weights[link.node_a] = round(
                weights.get(link.node_a, 0.0) + link.weight, 6)
            weights[link.node_b] = round(
                weights.get(link.node_b, 0.0) + link.weight, 6)
        for node_id in member_ids:
            weights.setdefault(node_id, 0.0)
        stats = community_stats(member_ids, internal)
        community_id = _new_community_id(member_ids, set())
        label = community_label(community_id, ordinal=index,
                                members=member_ids, internal_links=internal,
                                weights=weights, names=names, stats=stats)
        communities.append(BuiltCommunity(
            community_id=community_id, members=member_ids,
            member_weights={n: weights[n] for n in member_ids},
            stats=stats, label=label))
    return tuple(communities)


def _reassign_community_ids(communities: Sequence[BuiltCommunity],
                            ids: Sequence[str]) -> tuple[BuiltCommunity, ...]:
    """Проставляет сопоставленные `community_id` (members/веса не меняются)."""
    reassigned: list[BuiltCommunity] = []
    for community, community_id in zip(communities, ids):
        label = dataclasses.replace(community.label, community_id=community_id)
        reassigned.append(dataclasses.replace(
            community, community_id=community_id, label=label))
    return tuple(reassigned)


async def build_chat_communities(db, chat_id: int, *, now: int | None = None,
                                 build_id: str | None = None,
                                 raise_on_error: bool = False) -> BuildResult:
    """Собрать сообщества одного чата (детерминированно, без мутации памяти).

    Читает `nodes`/`edges`/`graph_facts`/`mca_associations` только на чтение,
    схлопывает идентичность через `entity_resolver`, пишет ТОЛЬКО две таблицы
    сообществ. Жизненный цикл — §6: строка `building` создаётся до расчёта,
    публикация полного набора членства и смена статусов — одной транзакцией;
    любое исключение/отмена/неполная публикация → `failed`, предыдущий
    `active` остаётся и не вытесняется.

    Гейт `MCA_MEMORY_COMMUNITIES_ENABLED` читает вызывающий (job/retrieval):
    у модуля нет второго механизма резолва гейтов, а сборщик никогда не
    вызывается на горячем пути (проверяется тестом).
    """
    started_at = int(now if now is not None else time.time())
    identifier = str(build_id or f"cb-{uuid.uuid4().hex}")

    revision = await _graph_revision(db, int(chat_id))
    nodes = await _read_nodes(db, int(chat_id))
    node_ids = [int(n["id"]) for n in nodes]
    names = {int(n["id"]): n["entity_name"] for n in nodes}
    prev_build_id = await _previous_active_build(db, int(chat_id))
    # Строка `building` создаётся ДО расчёта: любое падение дальше честно
    # переводит сборку в `failed`, не оставляя «висящего» состояния.
    await _create_build_row(
        db, build_id=identifier, chat_id=int(chat_id),
        graph_revision=revision, node_count=len(node_ids),
        edge_count=0, prev_build_id=prev_build_id,
        started_at=started_at)

    edge_count = 0
    provenance_counts: dict[str, int] = {k: 0 for k in PROVENANCE_WEIGHTS}
    try:
        canonical_rows = await _read_active_canonical_rows(db, int(chat_id))
        canonical, unresolved = await _resolve_canonical_ids(
            db, int(chat_id), nodes, canonical_rows)
        facts = await _read_facts(db, int(chat_id))
        associations = await _read_association_rows(db, int(chat_id))
        links, provenance_counts, dropped = await _collect_links(
            db, int(chat_id), nodes=nodes, canonical=canonical, facts=facts,
            associations=associations)
        edge_count = len(links)
        communities = _build_communities(node_ids=node_ids, links=links,
                                         names=names)
        prev_members = (await _read_build_members(db, int(chat_id),
                                                  prev_build_id)
                        if prev_build_id is not None else {})
        ids, change_summary = map_community_ids(
            [frozenset(c.members) for c in communities], prev_members)
        communities = _reassign_community_ids(communities, ids)
        # §14.2/§14.3: PROVEN/WEAK считается по настоящим метрикам сборки и
        # хранится в существующем `change_summary_json` (без DDL и без
        # per-community строк). Слабые в список не попадают вовсе: WEAK =
        # «всё, чего нет в списке», поэтому старые сборки без ключа читаются
        # как «ни одного proven» — честно, а не «всё proven».
        quality = [community_quality(c) for c in communities]
        proven = [q for q in quality
                  if q["status"] == COMMUNITY_STATUS_PROVEN]
        provenance_counts = dict(provenance_counts)
        provenance_counts["proven_communities"] = len(proven)
        provenance_counts["weak_communities"] = len(quality) - len(proven)
        change_summary = dict(change_summary)
        change_summary.update({
            "prev_build_id": prev_build_id,
            "algorithm": COMMUNITY_ALGORITHM,
            "algorithm_version": COMMUNITY_ALGORITHM_VERSION,
            "provenance_counts": dict(provenance_counts),
            "dropped_links": int(dropped),
            "unresolved_identity_nodes": list(unresolved),
            "node_count": len(node_ids),
            "edge_count": edge_count,
            "proven_community_ids": [q["community_id"] for q in proven],
            "proven_communities": proven,
        })
        finished_at = int(now if now is not None else time.time())
        await _publish_build(db, build_id=identifier, chat_id=int(chat_id),
                             communities=communities,
                             change_summary=change_summary,
                             node_count=len(node_ids),
                             edge_count=edge_count, finished_at=finished_at)
    except asyncio.CancelledError:
        await _mark_build_failed(db, chat_id=int(chat_id), build_id=identifier,
                                 error="cancelled",
                                 finished_at=int(time.time()))
        _emit("memory.community_build", outcome="cancelled",
              chat_id=int(chat_id), status=STATUS_FAILED,
              reason_code="cancelled")
        raise
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        await _mark_build_failed(db, chat_id=int(chat_id), build_id=identifier,
                                 error=error,
                                 finished_at=int(time.time()))
        _emit("memory.community_build", outcome="failure",
              chat_id=int(chat_id), status=STATUS_FAILED,
              reason_code=error[:_ERROR_MAX_CHARS])
        if raise_on_error:
            raise
        return BuildResult(
            build_id=identifier, chat_id=int(chat_id), status=STATUS_FAILED,
            graph_revision=revision, node_count=len(node_ids),
            edge_count=edge_count, prev_build_id=prev_build_id,
            communities=(), change_summary={},
            provenance_counts=dict(provenance_counts),
            error=error[:_ERROR_MAX_CHARS], started_at=started_at,
            finished_at=int(time.time()))

    _emit("memory.community_build", outcome="success", chat_id=int(chat_id),
          status=STATUS_ACTIVE,
          entity_ids={"build_id": identifier,
                      "communities": len(communities)})
    return BuildResult(
        build_id=identifier, chat_id=int(chat_id), status=STATUS_ACTIVE,
        graph_revision=revision, node_count=len(node_ids),
        edge_count=edge_count, prev_build_id=prev_build_id,
        communities=tuple(communities), change_summary=dict(change_summary),
        provenance_counts=dict(provenance_counts), error=None,
        started_at=started_at,
        finished_at=int(now if now is not None else time.time()))


__all__ = [
    "COMMUNITY_BUILDS_TABLE",
    "COMMUNITY_MEMBERS_TABLE",
    "COMMUNITIES_MIGRATION_STEP_NAME",
    "COMMUNITY_BUILDS_DDL_SQLITE",
    "COMMUNITY_MEMBERS_DDL_SQLITE",
    "COMMUNITY_INDEX_DDL",
    "STATUS_BUILDING",
    "STATUS_ACTIVE",
    "STATUS_SUPERSEDED",
    "STATUS_FAILED",
    "PROVENANCE_CONFIRMED",
    "PROVENANCE_TENTATIVE",
    "PROVENANCE_LEGACY",
    "PROVENANCE_COOCCURRENCE",
    "PROVENANCE_WEIGHTS",
    "LINK_SOURCE_EDGE",
    "LINK_SOURCE_ASSOCIATION",
    "COMMUNITY_ALGORITHM",
    "COMMUNITY_ALGORITHM_VERSION",
    "COMMUNITY_MAX_PASSES",
    "COMMUNITY_MIN_SIZE",
    "COMMUNITY_REUSE_OVERLAP",
    "COMMUNITY_DOMINANT_SHARE",
    "COMMUNITY_LABEL_MAX_NAMES",
    "REASON_SPLIT",
    "REASON_MERGE",
    "REASON_CREATED",
    "REASON_DROPPED",
    "NEUTRAL_LABEL_TEMPLATE",
    "UNKNOWN_VALUE_TEXT",
    "COMMUNITY_STATUS_PROVEN",
    "COMMUNITY_STATUS_WEAK",
    "COMMUNITY_PROVEN_MIN_SIZE",
    "COMMUNITY_PROVEN_MIN_STRONG_WEIGHT",
    "COMMUNITY_PROVEN_MIN_STRONG_SHARE",
    "classify_community_status",
    "community_status",
    "community_quality",
    "BUILD_PARAMS",
    "EvidenceLink",
    "CommunityStats",
    "CommunityLabel",
    "BuiltCommunity",
    "BuildResult",
    "fact_provenance",
    "link_weight",
    "association_provenance",
    "detect_communities",
    "map_community_ids",
    "community_stats",
    "community_label",
    "build_chat_communities",
]
