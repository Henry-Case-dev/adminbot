"""MEM-08-S2 — read-модель поиска и сообществ поверх СУЩЕСТВУЮЩЕГО retrieval.

Контракт: `plans/features/memory-cognitive-02/contracts.md` §4.3–§4.9, §6 C-6,
§9.5 и артефакт S1 `plans/features/memory-cognitive-02/search-read-model.md`.
Классификация Architect — **ARCH_REUSE_CONFIRMED**.

Что здесь есть (и чего нет):

* ``search_memory()`` — тонкий адаптер: он вызывает **ровно один** поисковый
  вход `services.mca_retrieval_context.retrieve` (§4.4/S-1) и превращает
  `RetrievalResult` в `memory_contracts.SearchResponse`. Своего поиска нет:
  ни FTS/`MATCH`, ни векторного канала, ни ранжирования — всё это уже внутри
  `retrieve`;
* ``read_active_communities()`` — read-модель семантических сообществ: читает
  ТОЛЬКО ``mca_community_builds.status='active'`` своего чата. Таблиц нет →
  ``state='unavailable'``; таблицы есть, сборки нет → ``state='no_active_build'``;
  есть active-сборка → реальные сообщества. Ни одно состояние не подменяется
  «пустым успехом» (§6/§4.7 S-4);
* LOD-тайлы (``agg:``) и клиентские компоненты связности (``cl:``) здесь не
  появляются: это техника рендера, а не сообщество (§4.6/INV-15);
* ноль LLM-вызовов, ноль мутаций памяти, ноль re-embed (§4.7 S-2).

Подпись сообщества пересчитывается **существующими** функциями
``memory_communities.community_stats``/``community_label`` (второй формулы
подписи нет) и только для сообществ, состав которых целиком помещается в
bounded-чтение; иначе подпись честно нейтральная (``label_kind='neutral'``) с
объяснением в ``label_basis`` — нейтральная подпись никогда не выдаётся за
семантическую категорию.
"""
from __future__ import annotations

import base64
import binascii
import dataclasses
import hashlib
import json
import logging

from services import mca_retrieval_context as _retrieval
from services import memory_communities as _communities
from services import memory_contracts as _mc
from services.relation_evidence import parse_edge_timestamp

logger = logging.getLogger(__name__)

# ── поиск: страница и пул (§4.4/§4.9) ───────────────────────────────────────

#: Сколько результатов показывается за одну страницу (панель 6–8, MEM-08.20).
SEARCH_PAGE_DEFAULT = 8
#: Верхняя граница страницы = верхняя граница UI-поиска (§4.1 `limit ≤ 20`).
SEARCH_PAGE_MAX = _mc.SEARCH_LIMIT_MAX
#: Пул одного запроса: единый `retrieve` возвращает не больше этого (§4.4).
SEARCH_POOL_LIMIT = _mc.SEARCH_LIMIT_MAX

# ── сообщества: bounded-чтение (§6, MEM-08.12/08.13) ────────────────────────

COMMUNITY_STATE_OK = "ok"
COMMUNITY_STATE_NO_ACTIVE_BUILD = "no_active_build"
COMMUNITY_STATE_UNAVAILABLE = "unavailable"

#: Разные причины одного и того же честного состояния (различаются в UI/логах).
COMMUNITY_REASON_TABLES_ABSENT = "tables_absent"
COMMUNITY_REASON_NO_ACTIVE_BUILD = "no_active_build"
COMMUNITY_REASON_SCOPE_GLOBAL = "scope_global"
COMMUNITY_REASON_READ_FAILED = "read_failed"

#: Сколько сообществ отдаёт карта (payload остаётся bounded).
COMMUNITY_READ_LIMIT = 24
#: Полный состав сообщества больше этого — подпись не пересчитывается.
COMMUNITY_LABEL_MEMBER_LIMIT = 200
#: Потолок внутренних связей для метрик подписи.
COMMUNITY_LINK_LIMIT = 2000

#: «Неизвестно» — то же значение, что в доме сообществ (не второй словарь).
UNKNOWN = _communities.UNKNOWN_VALUE_TEXT

_CURSOR_VERSION = 1
_CURSOR_MAX_CHARS = 512


class SearchRequestError(ValueError):
    """Невалидный вход запроса (эндпоинт отвечает 400, не «пустым поиском»)."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


# ── мелкие чтения (bounded SQL; это НЕ поиск) ───────────────────────────────

async def _fetchall(db, sql: str, params=()) -> list:
    cursor = await db.db.execute(sql, tuple(params))
    return list(await cursor.fetchall())


async def _fetchone(db, sql: str, params=()):
    rows = await _fetchall(db, sql, params)
    return rows[0] if rows else None


async def _tables_present(db, names: tuple[str, ...]) -> bool:
    marks = ",".join("?" for _ in names)
    row = await _fetchone(
        db,
        "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' "
        "AND name IN (" + marks + ")",
        list(names))
    return bool(row) and int(row["n"]) == len(names)


async def _table_counters(db, table: str) -> str:
    """Дешёвый отпечаток таблицы: ``кол-во`` + ``MAX(id)`` (для ревизии)."""
    try:
        row = await _fetchone(
            db, "SELECT COUNT(*) AS n, COALESCE(MAX(id), 0) AS m FROM " + table)
    except Exception:
        logger.debug("[memory_search] counters failed | table=%s", table,
                     exc_info=True)
        return f"{table}:n/a"
    if row is None:
        return f"{table}:n/a"
    return f"{table}:{int(row['n'])}:{int(row['m'])}"


async def _alias_counters(db) -> str:
    try:
        if not await _tables_present(db, ("mca_entity_canonical",)):
            return "alias:n/a"
        row = await _fetchone(
            db,
            "SELECT COUNT(*) AS n, COALESCE(MAX(rowid), 0) AS m "
            "FROM mca_entity_canonical")
    except Exception:
        logger.debug("[memory_search] alias counters unreadable", exc_info=True)
        return "alias:n/a"
    if row is None:
        return "alias:n/a"
    return f"alias:{int(row['n'])}:{int(row['m'])}"


async def _index_fingerprint(db) -> str:
    try:
        active = await db.get_active_embedding_generation("graph_facts_vec")
    except Exception:
        logger.debug("[memory_search] embedding generation unreadable",
                     exc_info=True)
        return "none"
    if active is None:
        return "none"
    fingerprint = active.get("fingerprint")
    return str(fingerprint) if fingerprint else "none"


async def _active_build_id(db, chat_id: int | None) -> str | None:
    """`build_id` активной сборки для эха ревизии; ошибка чтения → `None`."""
    if chat_id is None:
        return None
    try:
        if not await _tables_present(db, (_communities.COMMUNITY_BUILDS_TABLE,
                                         _communities.COMMUNITY_MEMBERS_TABLE)):
            return None
        row = await _fetchone(
            db,
            "SELECT build_id FROM " + _communities.COMMUNITY_BUILDS_TABLE +
            " WHERE chat_id = ? AND status = ? "
            "ORDER BY started_at DESC, build_id DESC LIMIT 1",
            (int(chat_id), _communities.STATUS_ACTIVE))
    except Exception:
        logger.debug("[memory_search] active build unreadable", exc_info=True)
        return None
    return str(row["build_id"]) if row else None


async def _revision(db, chat_id: int | None) -> _mc.SearchRevision:
    """Эхо ревизии чтения (§2.4.3/§4.9): токен консистентности, не ключ записи."""
    nodes = await _table_counters(db, "nodes")
    edges = await _table_counters(db, "edges")
    graph = hashlib.sha1(f"{nodes}|{edges}".encode("utf-8")).hexdigest()
    alias = hashlib.sha1((await _alias_counters(db)).encode("utf-8")).hexdigest()
    return _mc.SearchRevision(
        graph=graph, alias=alias,
        index_fingerprint=await _index_fingerprint(db),
        community_build=await _active_build_id(db, chat_id))


# ── read-модель сообществ (§6, три состояния) ───────────────────────────────

def _empty_communities(state: str, reason: str | None) -> dict:
    return {"state": state, "reason_code": reason, "build": None,
            "items": [], "total": 0, "shown": 0, "truncated": False}


def community_read_failure() -> dict:
    """Честный блок сообществ при сбое чтения (не «пустой успех»)."""
    return _empty_communities(COMMUNITY_STATE_UNAVAILABLE,
                              COMMUNITY_REASON_READ_FAILED)


async def _community_stats_and_label(db, *, chat_id: int, build_id: str,
                                     community_id: str, ordinal: int,
                                     member_count: int,
                                     member_rows: list[dict],
                                     associations_present: bool) -> dict:
    """Подпись и метрики ОДНОГО сообщества из реальных строк (без LLM).

    Переиспользует `memory_communities.community_stats` и
    `community_label`: второй формулы подписи не появляется. Если состав
    сообщества не поместился в bounded-чтение — подпись честно нейтральная.
    """
    member_ids = [int(r["node_id"]) for r in member_rows]
    weights = {int(r["node_id"]): float(r["member_weight"] or 0.0)
               for r in member_rows}
    truncated = len(member_rows) > COMMUNITY_LABEL_MEMBER_LIMIT
    if truncated:
        return {
            "label": _communities.NEUTRAL_LABEL_TEMPLATE.format(
                ordinal=int(ordinal)),
            "label_kind": "neutral",
            "label_basis": (
                f"подпись не пересчитана: состав сообщества ({int(member_count)} "
                f"узлов) больше предела чтения {COMMUNITY_LABEL_MEMBER_LIMIT}; "
                f"семантическая категория не подтверждена"),
            "dominant_names": [],
            "metrics": _unknown_metrics(),
            "metrics_basis": "unknown",
        }

    links = await _internal_links(db, chat_id=chat_id, member_ids=member_ids)
    stats = _communities.community_stats(member_ids, links)
    links_capped = len(links) > COMMUNITY_LINK_LIMIT
    if links_capped:
        stats = dataclasses.replace(stats, density=None)
    metrics = {
        "confirmed_links": int(stats.confirmed_links),
        "tentative_links": int(stats.tentative_links),
        "legacy_links": int(stats.legacy_links),
        "cooccurrence_links": int(stats.cooccurrence_links),
        "density": stats.density,
        "last_activity": stats.last_activity,
    }
    metrics_basis = "partial" if links_capped else "full"

    if associations_present:
        # Пары `mca_associations` (cooccurrence) входят в вес сборки, но
        # требуют резолва участников эпизодов — read-модель их не повторяет.
        # Значит доля доминирования НЕ воспроизводится: подпись честно
        # нейтральная, чтобы не выдать имя категорией, которой сборка не дала.
        return {
            "label": _communities.NEUTRAL_LABEL_TEMPLATE.format(
                ordinal=int(ordinal)),
            "label_kind": "neutral",
            "label_basis": (
                f"семантическая подпись не подтверждена: в чате есть пары "
                f"mca_associations (совпадения), а read-модель пересчитывает "
                f"только связи edges; узлов {int(member_count)}"),
            "dominant_names": [],
            "metrics": metrics,
            "metrics_basis": metrics_basis,
        }

    names: dict[int, str] = {}
    if member_ids:
        marks = ",".join("?" for _ in member_ids)
        for row in await _fetchall(
                db,
                "SELECT id, entity_name FROM nodes WHERE id IN (" + marks + ")",
                member_ids):
            names[int(row["id"])] = str(row["entity_name"] or "")
    label = _communities.community_label(
        community_id, ordinal=ordinal, members=member_ids,
        internal_links=links[:COMMUNITY_LINK_LIMIT], weights=weights,
        names=names, stats=stats)
    basis = (f"по активной сборке {build_id}: " + label.basis
             + ("; связи ограничены потолком чтения" if links_capped else ""))
    return {
        "label": label.label,
        "label_kind": "named" if label.dominant_names else "neutral",
        "label_basis": basis,
        "dominant_names": list(label.dominant_names),
        "metrics": metrics,
        "metrics_basis": metrics_basis,
    }


def _unknown_metrics() -> dict:
    return {"confirmed_links": None, "tentative_links": None,
            "legacy_links": None, "cooccurrence_links": None,
            "density": None, "last_activity": None}


async def _internal_links(db, *, chat_id: int, member_ids: list[int]) -> list:
    """Внутренние связи состава — существующими весами/классами §6."""
    if len(member_ids) < 2:
        return []
    marks = ",".join("?" for _ in member_ids)
    rows = await _fetchall(
        db,
        "SELECT e.source_id AS source_id, e.target_id AS target_id, "
        "e.fact_id AS fact_id, e.last_updated AS last_updated, "
        "f.subject_ref_id AS subject_ref_id, "
        "f.speaker_author_id AS speaker_author_id "
        "FROM edges e LEFT JOIN graph_facts f ON f.id = e.fact_id "
        "WHERE e.chat_id = ? AND e.source_id IN (" + marks + ") "
        "AND e.target_id IN (" + marks + ") "
        "ORDER BY e.id LIMIT ?",
        [int(chat_id)] + member_ids + member_ids
        + [COMMUNITY_LINK_LIMIT + 1])
    links = []
    for row in rows:
        fact_row = None
        if row["fact_id"] is not None:
            fact_row = {"subject_ref_id": row["subject_ref_id"],
                        "speaker_author_id": row["speaker_author_id"]}
        provenance_class = _communities.fact_provenance(fact_row)
        links.append(_communities.EvidenceLink(
            node_a=int(row["source_id"]), node_b=int(row["target_id"]),
            weight=_communities.link_weight(provenance_class),
            provenance=provenance_class,
            source=_communities.LINK_SOURCE_EDGE,
            last_activity=parse_edge_timestamp(row["last_updated"])))
    return links


async def _community_members(db, *, chat_id: int, build_id: str,
                             community_id: str) -> list[dict]:
    rows = await _fetchall(
        db,
        "SELECT node_id, member_weight FROM "
        + _communities.COMMUNITY_MEMBERS_TABLE +
        " WHERE chat_id = ? AND build_id = ? AND community_id = ? "
        "ORDER BY member_weight DESC, node_id ASC LIMIT ?",
        (int(chat_id), str(build_id), str(community_id),
         COMMUNITY_LABEL_MEMBER_LIMIT + 1))
    return [dict(row) for row in rows]


async def read_active_communities(db, chat_id: int | None, *,
                                  community_ids: tuple[str, ...] | None = None
                                  ) -> dict:
    """Сообщества АКТИВНОЙ сборки чата (три честных состояния).

    ``community_ids`` ограничивает набор (используется поиском для подписей
    уже найденных сообществ), ``None`` — весь bounded-набор карты.
    """
    if chat_id is None:
        return _empty_communities(COMMUNITY_STATE_NO_ACTIVE_BUILD,
                                  COMMUNITY_REASON_SCOPE_GLOBAL)
    chat_id = int(chat_id)
    try:
        present = await _tables_present(
            db, (_communities.COMMUNITY_BUILDS_TABLE,
                 _communities.COMMUNITY_MEMBERS_TABLE))
    except Exception:
        logger.warning("[memory_search] community tables unreadable",
                       exc_info=True)
        return _empty_communities(COMMUNITY_STATE_UNAVAILABLE,
                                  COMMUNITY_REASON_READ_FAILED)
    if not present:
        return _empty_communities(COMMUNITY_STATE_UNAVAILABLE,
                                  COMMUNITY_REASON_TABLES_ABSENT)

    try:
        build = await _fetchone(
            db,
            "SELECT build_id, algorithm, algorithm_version, graph_revision, "
            "node_count, edge_count, prev_build_id, status, started_at, "
            "finished_at FROM " + _communities.COMMUNITY_BUILDS_TABLE +
            " WHERE chat_id = ? AND status = ? "
            "ORDER BY started_at DESC, build_id DESC LIMIT 1",
            (chat_id, _communities.STATUS_ACTIVE))
    except Exception:
        logger.warning("[memory_search] active build unreadable", exc_info=True)
        return _empty_communities(COMMUNITY_STATE_UNAVAILABLE,
                                  COMMUNITY_REASON_READ_FAILED)
    if build is None:
        return _empty_communities(COMMUNITY_STATE_NO_ACTIVE_BUILD,
                                  COMMUNITY_REASON_NO_ACTIVE_BUILD)

    build_id = str(build["build_id"])
    sql = ("SELECT community_id, COUNT(*) AS member_count FROM "
           + _communities.COMMUNITY_MEMBERS_TABLE +
           " WHERE chat_id = ? AND build_id = ?")
    params: list = [chat_id, build_id]
    wanted = [str(cid) for cid in community_ids] \
        if community_ids is not None else None
    if wanted is not None:
        sql += " AND community_id IN (" + ",".join("?" for _ in wanted) + ")"
        params.extend(wanted)
    sql += " GROUP BY community_id ORDER BY community_id LIMIT ?"
    params.append(COMMUNITY_READ_LIMIT + 1)

    try:
        rows = ([dict(row) for row in await _fetchall(db, sql, params)]
                if wanted != [] else [])
    except Exception:
        logger.warning("[memory_search] community counts unreadable",
                       exc_info=True)
        return _empty_communities(COMMUNITY_STATE_UNAVAILABLE,
                                  COMMUNITY_REASON_READ_FAILED)

    truncated = len(rows) > COMMUNITY_READ_LIMIT
    total = len(rows) if not truncated else await _community_total(
        db, chat_id=chat_id, build_id=build_id, wanted=wanted)
    rows = rows[:COMMUNITY_READ_LIMIT]
    associations_present = await _associations_present(db, chat_id)
    items = []
    for ordinal, row in enumerate(rows, start=1):
        community_id = str(row["community_id"])
        member_count = int(row["member_count"])
        members = await _community_members(db, chat_id=chat_id,
                                           build_id=build_id,
                                           community_id=community_id)
        label = await _community_stats_and_label(
            db, chat_id=chat_id, build_id=build_id,
            community_id=community_id, ordinal=ordinal,
            member_count=member_count, member_rows=members,
            associations_present=associations_present)
        items.append({
            "community_id": community_id,
            "member_count": member_count,
            "label": label["label"],
            "label_kind": label["label_kind"],
            "label_basis": label["label_basis"],
            "dominant_names": label["dominant_names"],
            "metrics": label["metrics"],
            "metrics_basis": label["metrics_basis"],
        })

    return {
        "state": COMMUNITY_STATE_OK,
        "reason_code": None,
        "build": {
            "build_id": build_id,
            "algorithm": str(build["algorithm"] or ""),
            "algorithm_version": str(build["algorithm_version"] or ""),
            "graph_revision": str(build["graph_revision"] or ""),
            "status": str(build["status"] or ""),
            "node_count": int(build["node_count"] or 0),
            "edge_count": int(build["edge_count"] or 0),
            "prev_build_id": (str(build["prev_build_id"])
                              if build["prev_build_id"] is not None else None),
            "started_at": (int(build["started_at"])
                           if build["started_at"] is not None else None),
            "finished_at": (int(build["finished_at"])
                            if build["finished_at"] is not None else None),
        },
        "items": items,
        "total": int(total),
        "shown": len(rows),
        "truncated": truncated,
    }


async def _associations_present(db, chat_id: int) -> bool:
    """Есть ли в чате пары `mca_associations` (влияют на подпись сборки)."""
    try:
        if not await _tables_present(db, ("mca_associations",)):
            return False
        row = await _fetchone(
            db,
            "SELECT COUNT(*) AS n FROM mca_associations WHERE chat_id = ? "
            "AND status IN ('candidate','accepted')", (int(chat_id),))
    except Exception:
        logger.debug("[memory_search] associations unreadable", exc_info=True)
        return True                       # не знаем → подпись не подтверждаем
    return bool(row) and int(row["n"]) > 0


async def _community_total(db, *, chat_id: int, build_id: str,
                           wanted: list[str] | None) -> int:
    """Точное число сообществ активной сборки (не «показано+1»)."""
    sql = ("SELECT COUNT(DISTINCT community_id) AS n FROM "
           + _communities.COMMUNITY_MEMBERS_TABLE +
           " WHERE chat_id = ? AND build_id = ?")
    params: list = [chat_id, build_id]
    if wanted is not None:
        sql += " AND community_id IN (" + ",".join("?" for _ in wanted) + ")"
        params.extend(wanted)
    row = await _fetchone(db, sql, params)
    return int(row["n"]) if row is not None else 0


# ── поиск (§4.3–§4.9): ТОЛЬКО через единый retrieve ─────────────────────────

_CATEGORY_BY_NODE_TYPE = {
    "user": "Человек",
    "event": "Событие",
    "fact": "Факт",
    "topic": "Тема",
}
_CATEGORY_BY_ENTITY_TYPE = {
    "entity": "Тема",
    "graph_fact": "Факт",
    "episode": "Событие",
    "community": "Тема",
}
_REF_KIND_BY_ENTITY_TYPE = {
    "entity": _mc.RefKind.ENTITY,
    "graph_fact": _mc.RefKind.FACT,
    "episode": _mc.RefKind.EPISODE,
    "community": _mc.RefKind.COMMUNITY,
}
_CAUSE_BY_CHANNEL = {
    "exact": _mc.MatchCause.EXACT_NAME,
    "entity": _mc.MatchCause.ALIAS,
    "subject": _mc.MatchCause.ALIAS,
    "lexical": _mc.MatchCause.FTS,
    "vector": _mc.MatchCause.SEMANTIC,
    "reply_graph": _mc.MatchCause.RELATION_PATH,
    "episode": _mc.MatchCause.FTS,
    "community": _mc.MatchCause.COMMUNITY,
    "recent": _mc.MatchCause.TEMPORAL,
}
_FALLBACK_TITLE = "Без названия"


def _human(text: object, *, limit: int) -> str:
    """Человеческий текст без внутренних id/метрик (§7.2 R17, S-7).

    Правило одно на весь проект — `memory_contracts._INTERNAL_TOKEN_RE`
    (второй regex не заводится).
    """
    value = _mc._INTERNAL_TOKEN_RE.sub(" ", str(text or ""))
    value = " ".join(value.split())
    return value[:limit]


def _item_title(candidate) -> str:
    return _human(candidate.preview, limit=200) or _FALLBACK_TITLE


def _snippet(candidate) -> str | None:
    text = _human(candidate.preview, limit=_mc.preview_max_chars())
    return text or None


def _evidence_status(candidate) -> _mc.EvidenceStatus:
    if candidate.contradiction_status:
        return _mc.EvidenceStatus.CONTRADICTED
    if candidate.provenance_backed:
        return _mc.EvidenceStatus.CONFIRMED
    if candidate.entity_type == "graph_fact":
        return _mc.EvidenceStatus.LEGACY
    return _mc.EvidenceStatus.UNKNOWN


def _canonical_id(candidate, ref_kind: _mc.RefKind) -> str | None:
    entity_id = str(candidate.entity_id or "").strip()
    if ref_kind is _mc.RefKind.ENTITY:
        if candidate.id.startswith("ent:") and candidate.id.count(":") >= 2:
            return candidate.id
        if candidate.chat_id is None or not entity_id:
            return None
        return f"ent:{int(candidate.chat_id)}:{entity_id}"
    if ref_kind is _mc.RefKind.COMMUNITY:
        return f"comm:{entity_id}" if entity_id else None
    prefix = "fact" if ref_kind is _mc.RefKind.FACT else "episode"
    return f"{prefix}:{entity_id}" if entity_id else None


async def _node_types(db, node_ids: list[int]) -> dict[int, str]:
    if not node_ids:
        return {}
    marks = ",".join("?" for _ in node_ids)
    out: dict[int, str] = {}
    try:
        rows = await _fetchall(
            db, "SELECT id, entity_type FROM nodes WHERE id IN (" + marks + ")",
            node_ids)
    except Exception:
        logger.debug("[memory_search] node types unreadable", exc_info=True)
        return {}
    for row in rows:
        out[int(row["id"])] = str(row["entity_type"] or "")
    return out


def _focus(candidate, ref_kind: _mc.RefKind):
    """Куда навести карту; у факта без узла честный ``None`` (§4.3)."""
    if candidate.chat_id is None:
        return None
    if ref_kind is _mc.RefKind.ENTITY:
        try:
            node_id = int(candidate.entity_id)
        except (TypeError, ValueError):
            return None
        return _mc.SearchFocus(chat_id=int(candidate.chat_id), node_id=node_id)
    return None


def _community_labels(block: dict) -> dict[str, dict]:
    """`community_id → элемент` из блока сообществ (только `state='ok'`)."""
    if not block or block.get("state") != COMMUNITY_STATE_OK:
        return {}
    return {str(item["community_id"]): item for item in block.get("items") or ()}


async def _items_from_result(db, result, *, communities: dict[str, dict]
                             ) -> tuple[list, int]:
    """Кандидаты единого retrieval → типизированные `SearchItem`."""
    node_ids: list[int] = []
    for candidate in result.candidates:
        if candidate.entity_type == "entity":
            try:
                node_ids.append(int(candidate.entity_id))
            except (TypeError, ValueError):
                continue
    node_types = await _node_types(db, node_ids)

    items: list = []
    seen: set[str] = set()
    untyped = 0
    for candidate in result.candidates:
        ref_kind = _REF_KIND_BY_ENTITY_TYPE.get(candidate.entity_type)
        if ref_kind is None:
            # Сырое сообщение — не типизированный объект памяти (§4.3);
            # его текст остаётся доказательством, но не строкой выдачи.
            untyped += 1
            continue
        canonical_id = _canonical_id(candidate, ref_kind)
        if canonical_id is None or canonical_id in seen:
            continue
        seen.add(canonical_id)
        title = _item_title(candidate)
        snippet = _snippet(candidate)
        category = _CATEGORY_BY_ENTITY_TYPE[candidate.entity_type]
        if ref_kind is _mc.RefKind.ENTITY:
            try:
                node_type = node_types.get(int(candidate.entity_id), "")
            except (TypeError, ValueError):
                node_type = ""
            category = _CATEGORY_BY_NODE_TYPE.get(node_type, "Тема")
        elif ref_kind is _mc.RefKind.COMMUNITY:
            # Имя участника из канала — не подпись сообщества: без подписи
            # активной сборки честно нейтральное название, а не чужое имя.
            label = communities.get(str(candidate.entity_id)) or {}
            title = (str(label.get("label")) if label.get("label")
                     else _FALLBACK_TITLE)
            snippet = None
        try:
            items.append(_mc.SearchItem(
                ref_kind=ref_kind,
                canonical_id=canonical_id,
                title=title,
                category=category,
                match_cause=_CAUSE_BY_CHANNEL.get(candidate.channel,
                                                  _mc.MatchCause.FTS),
                evidence_status=_evidence_status(candidate),
                snippet=snippet,
                event_ts=(int(candidate.sent_at)
                          if int(candidate.sent_at or 0) > 0 else None),
                focus=_focus(candidate, ref_kind),
            ))
        except ValueError:
            logger.debug("[memory_search] item skipped | id=%s", canonical_id,
                         exc_info=True)
            continue
    return items, untyped


def _ambiguity(candidates, items) -> None:
    """Неоднозначность субъекта — вариантами, «популярный» не выбирается."""
    if not items:
        return
    variants = []
    for raw in candidates or ():
        try:
            canonical_id = str(raw.get("canonical_id") or "")
            variants.append(_mc.SearchVariant(
                canonical_id=canonical_id,
                title=_human(raw.get("title"), limit=200) or _FALLBACK_TITLE,
                discriminator=(_human(raw.get("discriminator"), limit=200)
                               or "вариант")))
        except (ValueError, AttributeError):
            continue
    unique: list = []
    seen: set[str] = set()
    for variant in variants:
        if variant.canonical_id in seen:
            continue
        seen.add(variant.canonical_id)
        unique.append(variant)
    if len(unique) < 2:
        return
    try:
        ambiguity = _mc.SearchAmbiguity(reason="несколько вариантов субъекта",
                                        variants=tuple(unique))
    except ValueError:
        return
    object.__setattr__(items[0], "ambiguity", ambiguity)


# ── курсор (§4.9) ──────────────────────────────────────────────────────────

def _query_hash(query: str) -> str:
    normalized = " ".join(str(query or "").casefold().split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _scope_token(chat_id: int | None) -> str:
    """Токен области в курсоре: страницы одного чата не смешиваются с scope_all."""
    if chat_id is None:
        return "scope_all"
    return f"chat:{int(chat_id)}"


def _revision_token(revision: _mc.SearchRevision) -> str:
    raw = "|".join([revision.graph, revision.alias,
                    revision.index_fingerprint,
                    str(revision.community_build or "none")])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _encode_cursor(*, query: str, scope: str, revision: str,
                   offset: int) -> str:
    payload = {"v": _CURSOR_VERSION, "q": _query_hash(query), "s": scope,
               "r": revision, "o": int(offset)}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    token = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")
    return token[:_CURSOR_MAX_CHARS]


def _decode_cursor(cursor: str) -> dict:
    if len(str(cursor)) > _CURSOR_MAX_CHARS:
        raise SearchRequestError("invalid_cursor")
    try:
        raw = base64.urlsafe_b64decode(str(cursor).encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise SearchRequestError("invalid_cursor") from None
    if not isinstance(data, dict) or data.get("v") != _CURSOR_VERSION:
        raise SearchRequestError("invalid_cursor")
    try:
        offset = int(data["o"])
    except (KeyError, TypeError, ValueError):
        raise SearchRequestError("invalid_cursor") from None
    if offset < 0:
        raise SearchRequestError("invalid_cursor")
    return {"q": data.get("q"), "s": data.get("s"), "r": data.get("r"),
            "o": offset}


# ── публичный вход ─────────────────────────────────────────────────────────

async def search_memory(db, memory, *, query: str, chat_id: int | None,
                        limit: int | None = None, cursor: str | None = None,
                        allowed_chat_ids: tuple[int, ...] | None = None
                        ) -> _mc.SearchResponse:
    """Единый поиск (§4.3): один `retrieve`, явные исходы, курсор ревизии.

    ``allowed_chat_ids`` — набор от ВЛАДЕЛЬЦА ПРАВ (§4.4/§4.7 S-3): если он
    передан и запрошенный чат в него не входит, ответ — `forbidden`/`no_rights`,
    а не «нет совпадений». ``None`` означает «владелец прав не ограничивает»
    (сегодня это глобальный администратор Memory-API).
    """
    text = " ".join(str(query or "").split())
    if not text:
        raise SearchRequestError("query_empty")
    if len(text) > _mc.SEARCH_QUERY_MAX_CHARS:
        raise SearchRequestError("query_too_long")
    page_size = SEARCH_PAGE_DEFAULT if limit is None else limit
    if isinstance(page_size, bool) or not isinstance(page_size, int) \
            or not 1 <= page_size <= SEARCH_PAGE_MAX:
        raise SearchRequestError("invalid_limit")

    if allowed_chat_ids is not None and chat_id is not None \
            and int(chat_id) not in {int(c) for c in allowed_chat_ids}:
        revision = await _revision(db, chat_id)
        return _mc.SearchResponse(
            status=_mc.SearchStatus.FORBIDDEN,
            query_state=_mc.QueryState.NO_RIGHTS,
            revision=revision, generation=0, scope=_scope(chat_id),
            reason_code="no_rights")

    chat_ids: tuple[int, ...] | None = None
    if chat_id is None:
        chat_ids = await scope_all_chat_ids(db)
        if allowed_chat_ids is not None:
            allowed = {int(c) for c in allowed_chat_ids}
            chat_ids = tuple(c for c in chat_ids if c in allowed)
        if not chat_ids:
            revision = await _revision(db, None)
            return _mc.SearchResponse(
                status=_mc.SearchStatus.EMPTY,
                query_state=_mc.QueryState.NO_MATCHES,
                revision=revision, generation=0,
                scope=_mc.SearchScope(mode=_mc.SearchScopeMode.SCOPE_ALL),
                reason_code="retrieval_empty")
    revision = await _revision(db, chat_id)
    scope_token = _scope_token(chat_id)
    offset = 0
    if cursor:
        data = _decode_cursor(cursor)
        if data["q"] != _query_hash(text) or data["s"] != scope_token:
            raise SearchRequestError("invalid_cursor")
        if data["r"] != _revision_token(revision):
            return _mc.SearchResponse(
                status=_mc.SearchStatus.CURSOR_STALE,
                query_state=_mc.QueryState.LOCAL_MATCHES,
                revision=revision, generation=0,
                scope=_scope(chat_id),
                reason_code="cursor_revision_mismatch")
        offset = int(data["o"])

    request = _retrieval.RetrievalRequest(
        chat_id=int(chat_id if chat_id is not None else chat_ids[0]),
        query=text,
        purpose=_mc.MemoryPurpose.UI_SEARCH.value,
        limit=SEARCH_POOL_LIMIT,
        mode="auto",
        chat_ids=chat_ids,
    )
    result = await _retrieval.retrieve(db, memory, request)
    if str(getattr(result, "status", "")) == _retrieval.RETRIEVAL_ERROR:
        return _mc.SearchResponse(
            status=_mc.SearchStatus.ERROR, query_state=_mc.QueryState.ERROR,
            revision=revision, generation=0, scope=_scope(chat_id),
            reason_code=str(getattr(result, "reason_code", None)
                            or "retrieval_error"))

    communities = await _communities_for_candidates(db, result)
    items, untyped = await _items_from_result(
        db, result, communities=_community_labels(communities))
    if offset > len(items):
        raise SearchRequestError("invalid_cursor")

    page = items[offset:offset + page_size]
    has_more = offset + len(page) < len(items)
    next_cursor = (_encode_cursor(query=text, scope=scope_token,
                                  revision=_revision_token(revision),
                                  offset=offset + len(page))
                  if has_more else None)

    # Неоднозначность прикрепляется ДО выбора исхода и только к элементам
    # текущей страницы: `status='ambiguous'` требует элемента с вариантами
    # (валидация `SearchResponse`), а показанные варианты должны быть видны.
    if getattr(result, "ambiguity", ()) and page:
        _ambiguity(getattr(result, "ambiguity", ()), page)
    ambiguous = any(item.ambiguity is not None for item in page)

    status, state, reason = _outcome(result, items, untyped,
                                     ambiguous=ambiguous)

    return _mc.SearchResponse(
        status=status, query_state=state, revision=revision, generation=0,
        scope=_scope(chat_id), items=tuple(page),
        next_cursor=next_cursor, has_more=has_more, reason_code=reason,
        debug=_debug(result, untyped, communities))


def _scope(chat_id: int | None) -> _mc.SearchScope:
    if chat_id is None:
        return _mc.SearchScope(mode=_mc.SearchScopeMode.SCOPE_ALL)
    return _mc.SearchScope(mode=_mc.SearchScopeMode.CHAT, chat_id=int(chat_id))


def _outcome(result, items: list, untyped: int, *, ambiguous: bool):
    if not items:
        if untyped:
            # Текстовые совпадения были, но типизированных объектов памяти нет:
            # это честный `no_matches` среди объектов, а не «ошибка».
            return (_mc.SearchStatus.EMPTY, _mc.QueryState.NO_MATCHES,
                    "untyped_text_matches_only")
        return (_mc.SearchStatus.EMPTY, _mc.QueryState.NO_MATCHES,
                str(getattr(result, "reason_code", None) or "retrieval_empty"))
    if ambiguous:
        return (_mc.SearchStatus.AMBIGUOUS, _mc.QueryState.CANDIDATES, None)
    if all(item.evidence_status is _mc.EvidenceStatus.LEGACY for item in items):
        return (_mc.SearchStatus.LEGACY_ONLY, _mc.QueryState.WEAK_LEGACY_ONLY,
                "legacy_only")
    return _mc.SearchStatus.OK, _mc.QueryState.CANDIDATES, None


def _debug(result, untyped: int, communities: dict) -> dict | None:
    """Админ-диагностика: каналы и причины, без текста переписки (R17)."""
    channels = list(getattr(result, "channels_used", ()) or ())
    return {
        "channels": channels,
        "retrieval_mode": str(getattr(result, "mode", "") or ""),
        "retrieval_reason": getattr(result, "reason_code", None),
        "untyped_matches": int(untyped),
        "community": ({"state": communities.get("state"),
                       "build_id": (communities.get("build") or {}).get(
                           "build_id")} if communities else None),
    }


async def _communities_for_candidates(db, result) -> dict:
    """Подписи уже найденных сообществ — из активной сборки, per chat."""
    by_chat: dict[int, set[str]] = {}
    for candidate in result.candidates:
        if candidate.entity_type != "community":
            continue
        if candidate.chat_id is None:
            continue
        by_chat.setdefault(int(candidate.chat_id), set()).add(
            str(candidate.entity_id))
    if not by_chat:
        return {}
    merged: list = []
    state = None
    build = None
    for chat_id, community_ids in sorted(by_chat.items()):
        block = await read_active_communities(
            db, chat_id, community_ids=tuple(sorted(community_ids)))
        if state is None:
            state = block.get("state")
            build = block.get("build")
        merged.extend(block.get("items") or ())
    return {"state": state, "build": build, "items": merged}


async def scope_all_chat_ids(db, *, limit: int = 200) -> tuple[int, ...]:
    """Разрешённый набор для ``scope_all`` — от владельца прав (global admin).

    В S2 владелец прав — глобальный администратор, поэтому набор = чаты,
    реально присутствующие в памяти. Ничего не угадывается: пустой набор
    даёт честный `no_matches`.
    """
    rows = []
    try:
        rows = await _fetchall(
            db,
            "SELECT chat_id FROM nodes WHERE chat_id IS NOT NULL "
            "UNION SELECT chat_id FROM graph_facts WHERE chat_id IS NOT NULL "
            "LIMIT ?", (int(limit),))
    except Exception:
        logger.warning("[memory_search] scope_all chat set unreadable",
                       exc_info=True)
        return ()
    out: list[int] = []
    for row in rows:
        try:
            chat = int(row["chat_id"])
        except (TypeError, ValueError):
            continue
        if chat not in out:
            out.append(chat)
    return tuple(out)


__all__ = [
    "COMMUNITY_STATE_OK",
    "COMMUNITY_STATE_NO_ACTIVE_BUILD",
    "COMMUNITY_STATE_UNAVAILABLE",
    "COMMUNITY_REASON_TABLES_ABSENT",
    "COMMUNITY_REASON_NO_ACTIVE_BUILD",
    "COMMUNITY_REASON_SCOPE_GLOBAL",
    "COMMUNITY_REASON_READ_FAILED",
    "SEARCH_PAGE_DEFAULT",
    "SEARCH_PAGE_MAX",
    "SEARCH_POOL_LIMIT",
    "SearchRequestError",
    "read_active_communities",
    "scope_all_chat_ids",
    "search_memory",
]
