"""MEMORY-03 (C-2) — доказательства ребра графа на СУЩЕСТВУЮЩЕМ механизме.

Ребро адресуется SourceRef'ом (`entity_type='graph_edge'`, `revision='stable'`),
каждое основание — строка `mca_evidence_links` с `link_type` из
`derived_from|supports|contradicts|mentions|supersedes` (§2.5). Новых таблиц,
колонок на `edges` и миграций НЕТ (MEM-03.2): `edges.fact_id` остаётся
совместимым полем, дополнительные основания идут в evidence-links.

Правила, которые держит этот модуль:
  * `mentions`/`cooccurrence`/`legacy_unknown` никогда не подтверждают ребро
    (R-11) и не понижают ребро с проверенным корнем (R-12) — слабые основания
    видны отдельно (`legacy_sources_count`, `has_unsupported_sources`);
  * собственный вывод бота (`origin='bot_self_reply'|'bot_direct_reply'`,
    `provenance.is_self_referential_origin`) пишется с
    `independence='self_referential'` и в независимую поддержку не входит
    (R-3): «бот уже так говорил» ≠ «это правда»;
  * транзитивность не выводится (R-5): `A–B` и `B–C` не дают `A–C`;
  * ревизия SourceRef ребра — константа (`'stable'`): повторная обработка того
    же сообщения/ребра не создаёт второй SourceRef и не раздувает
    `independent_support` (R-13, §2.4.1);
  * чтение объединяет ВСЕ ревизии SourceRef'ов ребра (§2.4.2) — «только самая
    свежая ревизия» запрещено;
  * счётчик независимых корней — один на проект
    (`provenance.evidence_independent_count`), поэтому слой данных и контракт
    (`RelationView.independent_support`) не могут разойтись.

Гейт: master `MCA_PROVENANCE_ENABLED` (`relation_evidence_enabled`). OFF →
никаких записей edge-evidence и пустое чтение (паритет baseline).
"""
from __future__ import annotations

import calendar
import hashlib
import logging
import time

from services import graphrag_provenance, provenance
from services.memory_contracts import (
    LEGACY_EXPLANATION,
    SUPPORTING_LINK_TYPES,
    OriginClass,
    RelationSourceView,
    RelationStatus,
    RelationView,
    resolve_assertion_mode,
)

logger = logging.getLogger(__name__)

EDGE_ENTITY_TYPE = "graph_edge"
NODE_ENTITY_TYPE = "entity"

# §2.1 «kind» основания — закрытый набор MEMORY-01.
_KIND_BY_ENTITY_TYPE = {
    "message": "message",
    "graph_fact": "graph_fact",
    "episode": "episode",
}

# Человеческие формулировки основания (без внутренних id/метрик, R17).
EXPLANATION_CONFIRMED = "Связь подтверждена независимыми источниками"
EXPLANATION_TENTATIVE = "Основания есть, но независимого подтверждения нет"
EXPLANATION_MENTIONS = "Только упоминание, не утверждение"
EXPLANATION_UNVERIFIED = "Связь записана без установленного происхождения"


def relation_evidence_enabled() -> bool:
    """Edge-evidence живёт на master-гейте `MCA_PROVENANCE_ENABLED`."""
    try:
        return provenance.provenance_enabled()
    except Exception:                                     # pragma: no cover
        return True


# ── Запись ──────────────────────────────────────────────────────────────────

async def resolve_edge_ref(db, chat_id: int, edge_id) -> int | None:
    """SourceRef ребра (get-or-create; `revision='stable'` — один на ребро)."""
    try:
        ref = provenance.graph_edge_source_ref(chat_id, edge_id)
    except ValueError:                                    # pragma: no cover
        return None
    return await provenance.resolve_source_ref(db, ref)


async def attach_edge_evidence(
        db, *, chat_id: int, edge_id, source_ref_id: int,
        link_type: str = "derived_from", method: str = "direct_reference",
        verification: str = "verified", independence: str = "independent",
        claim_key: str | None = None, basis: str | None = None,
        established_at: int = 0,
        extractor_version: str | None = None) -> int | None:
    """Привязать источник к ребру (идемпотентно по UNIQUE-индексу links).

    Возвращает `subject_ref_id` ребра либо `None` (гейт OFF / нет ребра-предмета).
    """
    if not relation_evidence_enabled():
        return None
    edge_ref = await resolve_edge_ref(db, chat_id, edge_id)
    if edge_ref is None:
        return None
    await provenance.add_evidence_link(db, provenance.EvidenceLink(
        subject_ref_id=int(edge_ref), source_ref_id=int(source_ref_id),
        link_type=link_type, method=method, verification=verification,
        independence=independence, claim_key=claim_key,
        extractor_version=extractor_version or provenance.EXTRACTOR_VERSION,
        basis=basis, established_at=int(established_at or 0)))
    return edge_ref


async def edge_ids_for_fact(db, chat_id: int, fact_id) -> list[int]:
    """Ребре(а), записанные из факта (`edges.fact_id`) — по индексу."""
    cursor = await db.db.execute(
        "SELECT id FROM edges WHERE fact_id = ? AND chat_id = ? "
        "ORDER BY id ASC", (int(fact_id), int(chat_id)))
    return [int(row["id"]) for row in await cursor.fetchall()]


async def attach_fact_edge_evidence(
        db, *, chat_id: int, fact_id, source_ref_id: int,
        origin: str | None = None, link_type: str = "derived_from",
        method: str = "direct_reference", verification: str = "verified",
        independence: str | None = None, claim_key: str | None = None,
        basis: str | None = "saved direct tg_message_id",
        established_at: int = 0,
        extractor_version: str | None = None) -> list[int]:
    """То же основание, что у факта, привязать к созданному из него ребру.

    R-3: origin ответа бота → `independence='self_referential'` всегда, даже
    если вызывающий передал `independent`: собственный вывод не corroborates
    сам себя. Возвращает id привязанных рёбер.
    """
    if not relation_evidence_enabled():
        return []
    self_referential = provenance.is_self_referential_origin(origin)
    if self_referential:
        # R-3: собственный вывод бота не corroborates сам себя. Связь
        # сохраняется (аудит «бот это говорил»), но независимой не является,
        # поэтому в `evidence_independent_count` не входит.
        effective_independence = "self_referential"
    else:
        effective_independence = independence or "independent"

    edge_ids = await edge_ids_for_fact(db, chat_id, fact_id)
    attached: list[int] = []
    for edge_id in edge_ids:
        edge_ref = await attach_edge_evidence(
            db, chat_id=chat_id, edge_id=edge_id, source_ref_id=source_ref_id,
            link_type=link_type, method=method,
            verification=verification, independence=effective_independence,
            claim_key=claim_key, basis=basis, established_at=established_at,
            extractor_version=extractor_version)
        if edge_ref is not None:
            attached.append(int(edge_id))
    if attached:
        _emit_edge_evidence(chat_id, attached, effective_independence)
    return attached


def _emit_edge_evidence(chat_id, edge_ids: list[int],
                        independence: str) -> None:
    """Наблюдаемость (§9): только числа/коды, без текста (R17). Fail-open.

    `reason_code` — из существующего закрытого набора (`provenance_linked`);
    новый код сюда не вводится (новые имена событий — MEMORY-09)."""
    try:
        from services import mca_events
        mca_events.emit_mca_event(
            "edge_evidence_attached", outcome="success",
            component="relation_evidence", chat_id=int(chat_id),
            reason_code="provenance_linked",
            usage_json={"edges": len(edge_ids),
                        "self_referential": int(
                            independence == "self_referential")})
    except Exception:                                     # pragma: no cover
        pass


# ── Чтение ──────────────────────────────────────────────────────────────────

async def edge_source_ref_ids(db, chat_id: int, edge_id) -> list[int]:
    """Все SourceRef ребра по ВСЕМ ревизиям (§2.4.2), не только 'stable'."""
    cursor = await db.db.execute(
        "SELECT source_ref_id FROM mca_source_refs WHERE store = 'sqlite' "
        "AND entity_type = ? AND entity_id = ? "
        "AND COALESCE(chat_id, -1) = COALESCE(?, -1) "
        "ORDER BY source_ref_id ASC",
        (EDGE_ENTITY_TYPE, str(int(edge_id)), chat_id))
    return [int(row["source_ref_id"]) for row in await cursor.fetchall()]


async def edge_links(db, chat_id: int, edge_id) -> list[dict]:
    """Объединение links всех SourceRef'ов ребра с дедупом по §2.4.2.

    Дедуп: `(source_ref_id, link_type, COALESCE(claim_key,''))`; порядок —
    `established_at`, затем `link_id` (детерминированно между запросами).
    """
    ref_ids = await edge_source_ref_ids(db, chat_id, edge_id)
    if not ref_ids:
        return []
    placeholders = ",".join("?" * len(ref_ids))
    cursor = await db.db.execute(
        "SELECT link_id, subject_ref_id, source_ref_id, link_type, method, "
        "verification, independence, claim_key, extractor_version, basis, "
        "checks_json, established_at FROM mca_evidence_links "
        f"WHERE subject_ref_id IN ({placeholders}) "
        "ORDER BY established_at ASC, link_id ASC", ref_ids)
    rows = [dict(r) for r in await cursor.fetchall()]
    seen: set = set()
    deduped: list[dict] = []
    for row in rows:
        key = (row.get("source_ref_id"), row.get("link_type"),
               row.get("claim_key") or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


async def _load_source_refs(db, ref_ids) -> dict[int, dict]:
    ids = sorted({int(v) for v in ref_ids if v is not None})
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    cursor = await db.db.execute(
        "SELECT source_ref_id, store, entity_type, entity_id, chat_id, "
        "revision, tg_message_id FROM mca_source_refs "
        f"WHERE source_ref_id IN ({placeholders})", ids)
    return {int(r["source_ref_id"]): dict(r) for r in await cursor.fetchall()}


def _int_entity_ids(refs: dict[int, dict], entity_type: str) -> list[int]:
    out: list[int] = []
    for ref in refs.values():
        if ref.get("entity_type") != entity_type:
            continue
        try:
            out.append(int(str(ref.get("entity_id"))))
        except (TypeError, ValueError):
            continue
    return out


async def _load_entity_rows(db, refs: dict[int, dict]) -> dict[tuple, dict]:
    """Строки источников (message/graph_fact) для вывода §2.2-сигналов."""
    rows: dict[tuple, dict] = {}
    message_ids = _int_entity_ids(refs, "message")
    if message_ids:
        placeholders = ",".join("?" * len(message_ids))
        cursor = await db.db.execute(
            "SELECT id, is_forward, forward_source, timestamp, author_name "
            f"FROM smart_messages WHERE id IN ({placeholders})", message_ids)
        for row in await cursor.fetchall():
            data = dict(row)
            rows[("message", str(int(data["id"])))] = data
    fact_ids = _int_entity_ids(refs, "graph_fact")
    if fact_ids:
        placeholders = ",".join("?" * len(fact_ids))
        cursor = await db.db.execute(
            "SELECT id, origin, perspective, attribution_method, "
            "provenance_channel, forward_from, created_at, valid_from "
            f"FROM graph_facts WHERE id IN ({placeholders})", fact_ids)
        for row in await cursor.fetchall():
            data = dict(row)
            rows[("graph_fact", str(int(data["id"])))] = data
    return rows


def _source_kind(ref: dict) -> str:
    """`kind` основания (§2.1): bot-output отличается от человеческого слова."""
    entity_id = str(ref.get("entity_id") or "")
    if entity_id.startswith("bot_output:"):
        return "bot_output"
    return _KIND_BY_ENTITY_TYPE.get(str(ref.get("entity_type")), "message")


def _assertion_mode_for(entity_type: str | None, row: dict):
    if not row:
        return resolve_assertion_mode()
    if entity_type == "message":
        return resolve_assertion_mode(
            forwarded=bool(row.get("is_forward")),
            forward_from=str(row.get("forward_source") or ""))
    return resolve_assertion_mode(
        forward_from=str(row.get("forward_from") or ""),
        perspective=row.get("perspective"),
        attribution_method=row.get("attribution_method"),
        provenance_channel=row.get("provenance_channel"),
        origin=row.get("origin"))


def _origin_class(entity_type: str | None, row: dict,
                  link: dict) -> OriginClass:
    value = graphrag_provenance.classify_origin_class(
        entity_type=entity_type, source_row=row,
        link_type=str(link.get("link_type") or ""),
        method=str(link.get("method") or "unknown"),
        verification=str(link.get("verification") or "unknown"))
    try:
        return OriginClass(value)
    except ValueError:                                    # pragma: no cover
        return OriginClass.LEGACY_UNKNOWN


def _source_view(link: dict, ref: dict, row: dict) -> RelationSourceView:
    entity_type = str(ref.get("entity_type") or "")
    settled_at = int(link.get("established_at") or 0) or int(time.time())
    return RelationSourceView(
        link_type=str(link.get("link_type") or ""),
        origin_class=_origin_class(entity_type, row, link),
        verification=str(link.get("verification") or "unknown"),
        independence=str(link.get("independence") or "unknown"),
        established_at=max(1, settled_at),
        method=str(link.get("method") or "unknown"),
        kind=_source_kind(ref),
        assertion_mode=_assertion_mode_for(entity_type, row),
        source_ref_id=int(link["source_ref_id"]),
        fact_id=_event_fact_id(ref, row),
        speaker=row.get("author_name") if entity_type == "message" else None,
        subject=None,                      # субъект — свойство факта, не связи
        asserted_ts=(int(row["timestamp"])
                     if entity_type == "message" and row.get("timestamp")
                     else None),
        event_ts=(_opt_int(row.get("valid_from"))
                  if entity_type == "graph_fact" else None),
        observed_ts=_opt_int(link.get("established_at")),
    )


def _event_fact_id(ref: dict, row: dict) -> int | None:
    if str(ref.get("entity_type") or "") != "graph_fact":
        return None
    return _opt_int(row.get("id")) if row else _opt_int(ref.get("entity_id"))


def _opt_int(value) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _status_from_sources(sources: list[RelationSourceView]) -> RelationStatus:
    if any(s.counts_as_independent for s in sources):
        return RelationStatus.CONFIRMED
    if any(s.link_type in SUPPORTING_LINK_TYPES for s in sources):
        return RelationStatus.TENTATIVE
    return RelationStatus.UNVERIFIED


def _explanation_for(status: RelationStatus, sources: list[RelationSourceView],
                     *, bare: bool = False) -> str:
    if status is RelationStatus.CONFIRMED:
        return EXPLANATION_CONFIRMED
    if status is RelationStatus.TENTATIVE:
        return EXPLANATION_TENTATIVE
    if sources and all(s.link_type == "mentions" for s in sources):
        return EXPLANATION_MENTIONS
    if bare:
        return LEGACY_EXPLANATION
    return EXPLANATION_UNVERIFIED


async def edge_evidence(db, *, chat_id: int, edge_id) -> dict:
    """Данные карточки ребра: все основания + честные счётчики (§2.1/§2.8).

    `independent_support` — из ОБЩЕГО счётчика `provenance.evidence_independent_count`
    (union links), `legacy_sources_count` — отдельно; слабое основание никогда
    не понижает ребро с проверенным корнем (R-12).
    """
    links = await edge_links(db, chat_id, edge_id)
    refs = await _load_source_refs(db, [l.get("source_ref_id") for l in links])
    rows = await _load_entity_rows(db, refs)
    sources: list[RelationSourceView] = []
    unmapped: list[dict] = []
    for link in links:
        ref = refs.get(int(link["source_ref_id"]))
        if ref is None:
            unmapped.append({"source_ref_id": link.get("source_ref_id"),
                             "link_type": link.get("link_type"),
                             "reason_code": "source_ref_missing"})
            continue
        row = rows.get((str(ref.get("entity_type")),
                        str(ref.get("entity_id"))))
        try:
            sources.append(_source_view(link, ref, row or {}))
        except ValueError:
            logger.debug("[relation_evidence] source view rejected | link=%s",
                         link.get("link_id"), exc_info=True)
            unmapped.append({"source_ref_id": link.get("source_ref_id"),
                             "link_type": link.get("link_type"),
                             "reason_code": "source_unresolvable"})
    independent = int(provenance.evidence_independent_count(links))
    status = _status_from_sources(sources)
    legacy_count = sum(1 for s in sources
                       if s.origin_class is OriginClass.LEGACY_UNKNOWN)
    mentions_only = bool(sources) and all(s.link_type == "mentions"
                                          for s in sources)
    bare_legacy = not sources and not unmapped
    return {
        "edge_id": int(edge_id),
        "chat_id": int(chat_id),
        "sources": [s.as_dict() for s in sources],
        "unmapped_sources": unmapped,
        "independent_support": independent,
        "contract_independent_support": _view_support(sources),
        "legacy_sources_count": legacy_count,
        "mentions_only": mentions_only,
        "bare_legacy": bare_legacy,
        "has_unsupported_sources": (independent == 0 or legacy_count > 0
                                    or mentions_only),
        "status": status.value,
        "explanation": _explanation_for(status, sources, bare=bare_legacy),
    }


def _view_support(sources: list[RelationSourceView]) -> int:
    """Независимые корни по контракту (`RelationSourceView.counts_as_independent`).

    Обязан совпадать с `independent_support` — расхождение означает, что слой
    данных и контракт разошлись (наблюдаемое, а не «на глаз»)."""
    return len({s.root_key for s in sources if s.counts_as_independent})


# ── Ревизия графа и карточка ребра ──────────────────────────────────────────

async def graph_revision(db, chat_id: int) -> str:
    """Дешёвый вычисляемый дайджест состава графа чата (§2.4.3). Нигде не хранится."""
    cursor = await db.db.execute(
        "SELECT (SELECT COUNT(*) FROM nodes WHERE chat_id = ?), "
        "(SELECT COALESCE(MAX(id), 0) FROM nodes WHERE chat_id = ?), "
        "(SELECT COUNT(*) FROM edges WHERE chat_id = ?), "
        "(SELECT COALESCE(MAX(id), 0) FROM edges WHERE chat_id = ?), "
        "(SELECT COALESCE(MAX(last_updated), '') FROM edges WHERE chat_id = ?)",
        (int(chat_id),) * 5)
    row = await cursor.fetchone()
    parts = [str(row[0]), str(row[1]), str(row[2]), str(row[3]),
             str(row[4] or "")]
    material = ":".join(parts)
    return hashlib.sha1(material.encode("utf-8")).hexdigest()


def parse_edge_timestamp(value) -> int | None:
    """`edges.last_updated` (TEXT UTC) → unix; непознанное → None (не выдумываем)."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value) or None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return int(calendar.timegm(time.strptime(text, fmt)))
        except ValueError:
            continue
    return None


async def build_relation_view(db, *, chat_id: int, edge_id) -> RelationView | None:
    """Логическое ребро (§2.1) для карточки. Нет строки ребра → None."""
    cursor = await db.db.execute(
        "SELECT id, chat_id, source_id, target_id, relation_type, weight, "
        "last_updated, fact_id FROM edges WHERE id = ? AND chat_id = ?",
        (int(edge_id), int(chat_id)))
    edge = await cursor.fetchone()
    if edge is None:
        return None
    edge = dict(edge)
    evidence = await edge_evidence(db, chat_id=chat_id, edge_id=edge_id)
    sources = tuple(_sources_from_dicts(evidence["sources"]))
    status = RelationStatus(evidence["status"])
    return RelationView(
        edge_id=int(edge["id"]),
        chat_id=int(edge["chat_id"]),
        source_entity_id=int(edge["source_id"]),
        target_entity_id=int(edge["target_id"]),
        relation_type=str(edge["relation_type"]),
        relation_label=str(edge["relation_type"]),
        status=status,
        sources=sources,
        frequency=max(0, int(float(edge.get("weight") or 0))),
        explanation=evidence["explanation"],
        edge_updated_at=parse_edge_timestamp(edge.get("last_updated")),
        graph_revision=await graph_revision(db, chat_id),
    )


def _sources_from_dicts(items) -> list[RelationSourceView]:
    return [RelationSourceView.from_dict(item) for item in items or ()]
