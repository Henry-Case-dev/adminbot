"""EPIC-MEMORY-COGNITIVE-02 / MEMORY-02 (часть B) — дубли сущностей.

Источник: `plans/features/memory-cognitive-02/contracts.md` (rev3) §1.2/§1.2.1
(кто доказывает тождество), §1.3 (ID-3 «никогда не сливает», ID-4 casefold не
доказывает тождество, ID-8/ID-11), §1.4 (member→canonical — аддитивная строка,
данные не переписываются), §1.4.2 (глубина redirect 1, циклы), §2.5
(агрегированное ребро после слияния), §5.3 B1/B2 (dry-run, чекпоинты, resume).
Требования источника: MEM-02.6 (dry-run + безопасные слияния), MEM-02.7
(повторный запуск не множит узлы/рёбра), MEM-02.8 (отрицательные случаи).

Границы (проверяется ревью):

* **Ничего не удаляется.** Слияние — это ОДНА аддитивная строка
  `mca_entity_canonical` (`member_node_id` → `canonical_node_id`). Строки
  `nodes`/`edges`/`graph_facts` не переписываются и не удаляются, поэтому
  `fact_id`, веса, `expires_at`/`valid_*`, статусы и evidence-связи остаются
  валидными; откат — `status='revoked'` (аудит `legacy_id → canonical_id`
  сохраняется в самой строке).
* **Похожесть не доказывает тождество.** Векторное сходство в решениях не
  участвует вообще (модуль не импортирует embeddings и не читает `*_vec`);
  casefold/написание — только причина ПОКАЗАТЬ пару, не применить слияние.
* **Доказательство — устойчивая идентичность Telegram.** Пара безопасна,
  только если оба узла доказанно принадлежат одному `user_id` (`author_name`
  в `smart_messages` + действующий alias-каскад) и ни один из узлов не
  закреплён за другим uid. Два uid с одинаковым именем остаются
  `ambiguous` (никогда не сливаются) — §1.2.1/EVAL-04.
* **Dry-run только читает**: ни одной записи, ни одного `write_transaction`.

Модуль не создаёт узлов и не меняет поведение писателей W1–W6: он добавляет
redirect-строки, которые видны резолверу (`entity_resolver`) при включённом
гейте `MCA_MEMORY_IDENTITY_ENABLED`.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import sqlite3
import time
import unicodedata
from typing import Any, Iterable, Sequence

from services import entity_resolver as er
from services import mca_gates

logger = logging.getLogger(__name__)

MERGE_TABLE = er.ENTITY_CANONICAL_TABLE

# ── причины/вердикты пары (закрытые строковые значения) ────────────────────
REASON_SAME_FOLDED_NAME = "same_folded_name"
REASON_STABLE_IDENTITY = "stable_identity_match"
REASON_SOURCE_OVERLAP = "shared_source_overlap"
REASON_IDENTITY_NOT_PROVEN = "identity_not_proven"
REASON_IDENTITY_AMBIGUOUS = "identity_ambiguous_multiple_uids"
REASON_IDENTITY_PINNED_ELSEWHERE = "identity_pinned_to_other_uid"
REASON_NODE_MISSING = "node_missing"
REASON_TYPE_CONFLICT = "entity_type_conflict"
REASON_SAME_NODE = "same_node"
REASON_REDIRECT_CHAIN = "redirect_chain_not_flattened"
REASON_REDIRECT_CYCLE = "redirect_cycle_detected"
REASON_ALREADY_MERGED = "already_merged"
REASON_MERGE_CONFLICT = "merge_target_conflict"
REASON_MERGED = "merged"
REASON_REVOKED = "revoked"
REASON_DRY_RUN = "dry_run"
REASON_GATE_OFF = "identity_gate_off"

PAIR_SAFE = "safe"
PAIR_AMBIGUOUS = "ambiguous"
PAIR_REFUSED = "refused"

#: Границы отчёта (backfill не «дочитывает всё»: числа видны и честны).
MAX_PAIRS_PER_CHAT = 200
MAX_NODES_SCAN = 20000
MAX_PAIRS_PER_GROUP = 8
MAX_NODE_UID_EVIDENCE_ROWS = 5000
#: Потолок строк индекса «источник → узлы» на чат (bounded backfill-чтение).
MAX_SOURCE_INDEX_ROWS = 20000
MAX_PAIR_PREVIEW = 50

#: Идентификаторы durable-чекпоинта в СУЩЕСТВУЮЩЕЙ очереди `task_jobs` (v14):
#: новой таблицы чекпоинтов контракт §5.1 не разрешает.
MERGE_JOB_ID = "memory_identity_merge"
MERGE_JOB_OWNER = "memory_identity"
MERGE_JOB_KIND = "memory_identity_merge"


# ── утилиты чтения строк ───────────────────────────────────────────────────

async def _fetchall(db, sql: str, params: Iterable[Any] = ()) -> list[Any]:
    cursor = await db.db.execute(sql, tuple(params))
    return list(await cursor.fetchall())


async def _fetchone(db, sql: str, params: Iterable[Any] = ()):
    cursor = await db.db.execute(sql, tuple(params))
    return await cursor.fetchone()


def _col(row, key: str, index: int = 0):
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return row[index]


def _fold(name: str) -> str:
    """Сравнительный ключ группировки: NFC + trim + casefold (ТОЛЬКО показ)."""
    return unicodedata.normalize("NFC", str(name)).strip().casefold()


def _emit(event_name: str, *, outcome: str = "success", **fields: Any) -> None:
    try:
        from services import mca_events
        mca_events.emit_mca_event(event_name, outcome=outcome,
                                  component="entity_merge", **fields)
    except Exception:          # pragma: no cover — телеметрия fail-open
        logger.debug("[entity_merge] event failed | %s", event_name,
                     exc_info=True)


# ── доказательство идентичности (только существующие данные) ───────────────

async def _author_name_index(db, chat_id: int, names: Sequence[str]
                             ) -> tuple[dict[str, set[int]], bool]:
    """`author_name → {user_id}` по `smart_messages` (bounded, только кандидаты).

    Возвращает `(индекс, truncated)`. Пустой `names` → пустой индекс без SQL.
    """
    unique = [n for n in dict.fromkeys(str(n) for n in names if n)]
    if not unique:
        return {}, False
    index: dict[str, set[int]] = {}
    truncated = len(unique) > MAX_NODE_UID_EVIDENCE_ROWS
    chunk = unique[:MAX_NODE_UID_EVIDENCE_ROWS]
    placeholders = ", ".join("?" for _ in chunk)
    rows = await _fetchall(
        db,
        "SELECT user_id, author_name FROM smart_messages "
        "WHERE chat_id = ? AND user_id IS NOT NULL "
        f"AND author_name IN ({placeholders}) GROUP BY user_id, author_name",
        (int(chat_id), *chunk),
    )
    for row in rows:
        name = _col(row, "author_name", 1)
        uid = _col(row, "user_id", 0)
        if name is None or uid is None:
            continue
        index.setdefault(str(name), set()).add(int(uid))
    return index, truncated


async def _uid_display_names(db, chat_id: int, uids: Iterable[int]
                             ) -> dict[int, set[str]]:
    """Отображаемые имена uid по действующему каскаду `summary_aliases`.

    Второго словаря алиасов нет (INV-03): используется существующий
    `AliasResolver`. Недоступный каскад → пустая карта (кандидаты по имени
    остаются, но доказательство uid пойдёт только по `author_name`).
    """
    wanted = sorted({int(u) for u in uids})
    if not wanted:
        return {}
    try:
        from services.summary_aliases import build_alias_resolver
        resolver = await build_alias_resolver(int(chat_id))
    except Exception:
        logger.warning("[entity_merge] alias resolver unavailable | chat=%s",
                       chat_id, exc_info=True)
        return {}
    names: dict[int, set[str]] = {}
    for uid in wanted:
        try:
            resolved = str(resolver.resolve(uid) or "").strip()
        except Exception:      # pragma: no cover — защитная ветка
            resolved = ""
        if not resolved:
            continue
        bucket = names.setdefault(uid, set())
        bucket.add(resolved)
        try:
            canonical = str(resolver.canon_name(resolved) or "").strip()
        except Exception:      # pragma: no cover — защитная ветка
            canonical = ""
        if canonical:
            bucket.add(canonical)
    return names


async def _chat_uids(db, chat_id: int) -> list[int]:
    """uid чата по `users_meta` (авторитетный список, §1.2.1)."""
    try:
        rows = await _fetchall(
            db,
            "SELECT DISTINCT user_id FROM users_meta WHERE chat_id = ? "
            "AND user_id IS NOT NULL ORDER BY user_id",
            (int(chat_id),),
        )
    except Exception:          # pragma: no cover — старая/урезанная БД
        return []
    return [int(_col(row, "user_id", 0)) for row in rows]


async def _active_merge_rows(db, chat_id: int, entity_type: str) -> list[Any]:
    """Активные строки `mca_entity_canonical` чата/типа (таблица может не быть)."""
    try:
        return await _fetchall(
            db,
            f"SELECT member_node_id, canonical_node_id, stable_kind, "
            f"stable_value, resolution FROM {MERGE_TABLE} "
            "WHERE chat_id = ? AND entity_type = ? AND status = ?",
            (int(chat_id), str(entity_type), er.STATUS_ACTIVE),
        )
    except sqlite3.OperationalError:
        # БД до миграции v43: идентичности нет — доказывать нечем.
        return []


class _IdentityEvidence:
    """Карта `узел → uid` и `узел → активные закреплённые uid` для чата."""

    def __init__(self) -> None:
        self.node_uids: dict[int, set[int]] = {}
        self.node_claims: dict[int, set[int]] = {}
        self.node_redirections: dict[int, int] = {}
        self.truncated = False

    def uids(self, node_id: int) -> tuple[int, ...]:
        return tuple(sorted(self.node_uids.get(node_id, ())))

    def claims(self, node_id: int) -> tuple[int, ...]:
        return tuple(sorted(self.node_claims.get(node_id, ())))

    def redirect(self, node_id: int) -> int | None:
        return self.node_redirections.get(node_id)

    def terminal(self, node_id: int) -> int:
        """Последний достижимый узел по активным строкам (глубина 1, §1.4.2).

        Автоматического «выпрямления» нет: цепочка лишь читается до конца
        (с защитой от цикла), данные не переписываются.
        """
        current = int(node_id)
        visited = {current}
        steps = 0
        while steps < 8:
            nxt = self.node_redirections.get(current)
            if nxt is None or nxt == current or nxt in visited:
                break
            visited.add(nxt)
            current = nxt
            steps += 1
        return current


async def _collect_identity_evidence(db, chat_id: int, entity_type: str,
                                     nodes: Sequence["_Node"],
                                     ) -> _IdentityEvidence:
    """Доказательство uid для конкретных узлов (bounded, только кандидаты)."""
    evidence = _IdentityEvidence()
    if not nodes:
        return evidence
    names = [node.entity_name for node in nodes]
    index, truncated = await _author_name_index(db, chat_id, names)
    evidence.truncated = truncated

    uids: set[int] = set()
    for values in index.values():
        uids |= values
    display = await _uid_display_names(db, chat_id,
                                       uids | set(await _chat_uids(db, chat_id)))
    for uid, display_names in display.items():
        for name in display_names:
            index.setdefault(name, set()).add(uid)

    for node in nodes:
        found = index.get(node.entity_name)
        if found:
            evidence.node_uids[node.node_id] = set(found)

    for row in await _active_merge_rows(db, chat_id, entity_type):
        member_id = int(_col(row, "member_node_id", 0))
        canonical_id = int(_col(row, "canonical_node_id", 1))
        value = _col(row, "stable_value", 3)
        kind = _col(row, "stable_kind", 2)
        evidence.node_redirections[member_id] = canonical_id
        if kind == er.STABLE_KIND_TG_USER and value is not None:
            uid = int(str(value))
            evidence.node_claims.setdefault(member_id, set()).add(uid)
            evidence.node_claims.setdefault(canonical_id, set()).add(uid)
    return evidence


# ── отчёт о кандидатах (B1: dry-run) ───────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class _Node:
    node_id: int
    entity_name: str
    entity_type: str


async def _chat_nodes(db, chat_id: int, entity_type: str,
                      *, limit: int) -> tuple[list[_Node], bool]:
    rows = await _fetchall(
        db,
        "SELECT id, entity_name, entity_type FROM nodes "
        "WHERE chat_id = ? AND entity_type = ? ORDER BY id LIMIT ?",
        (int(chat_id), str(entity_type), int(limit) + 1),
    )
    truncated = len(rows) > limit
    nodes = [
        _Node(int(_col(row, "id", 0)),
              str(_col(row, "entity_name", 1)),
              str(_col(row, "entity_type", 2)))
        for row in rows[:limit]
    ]
    return nodes, truncated


async def _source_buckets(db, chat_id: int) -> dict[int, dict[str, set]]:
    """`tg_message_id → {ids, names}` по фактам чата (один bounded SELECT).

    Источник третьей причины показать пару (§5.3 B1 «по chat/type, алиасам и
    источникам»): оба узла упомянуты фактами одного исходного сообщения. Это
    НЕ доказательство тождества — только причина показать пару. Индекс
    строится один раз на чат, а не на каждую пару.
    """
    try:
        rows = await _fetchall(
            db,
            "SELECT tg_message_id AS tg, subject_ref_id AS sref, "
            "target_user AS tuser FROM graph_facts "
            "WHERE chat_id = ? AND tg_message_id IS NOT NULL LIMIT ?",
            (int(chat_id), MAX_SOURCE_INDEX_ROWS),
        )
    except sqlite3.OperationalError:      # pragma: no cover — до v31
        return {}
    buckets: dict[int, dict[str, set]] = {}
    for row in rows:
        tg = _col(row, "tg", 0)
        if tg is None:
            continue
        bucket = buckets.setdefault(int(tg), {"ids": set(), "names": set()})
        sref = _col(row, "sref", 1)
        if sref is not None:
            bucket["ids"].add(int(sref))
        tuser = _col(row, "tuser", 2)
        if tuser is not None:
            bucket["names"].add(str(tuser))
    return buckets


def _shares_source(buckets: dict[int, dict[str, set]], first: _Node,
                   second: _Node) -> bool:
    """Есть сообщение, факты которого ссылаются на ОБА узла."""
    for bucket in buckets.values():
        ids, names = bucket["ids"], bucket["names"]
        if (first.node_id in ids or first.entity_name in names) and \
                (second.node_id in ids or second.entity_name in names):
            return True
    return False


async def _node_impact(db, chat_id: int, node: _Node,
                       entity_type: str) -> dict:
    """Что ссылается на узел: рёбра/факты/источники (влияние слияния)."""
    impact = {"edges": 0, "facts": 0, "source_refs": 0, "target_user_facts": 0}
    try:
        row = await _fetchone(
            db,
            "SELECT COUNT(*) AS n FROM edges WHERE chat_id = ? "
            "AND (source_id = ? OR target_id = ?)",
            (int(chat_id), node.node_id, node.node_id))
        impact["edges"] = int(_col(row, "n", 0) or 0)
    except sqlite3.OperationalError:      # pragma: no cover — урезанная БД
        pass
    try:
        row = await _fetchone(
            db,
            "SELECT COUNT(*) AS n FROM graph_facts "
            "WHERE chat_id = ? AND subject_ref_id = ?",
            (int(chat_id), node.node_id))
        impact["facts"] = int(_col(row, "n", 0) or 0)
    except sqlite3.OperationalError:      # pragma: no cover — до v31
        pass
    if entity_type == "user":
        try:
            row = await _fetchone(
                db,
                "SELECT COUNT(*) AS n FROM graph_facts "
                "WHERE chat_id = ? AND target_user = ?",
                (int(chat_id), node.entity_name))
            impact["target_user_facts"] = int(_col(row, "n", 0) or 0)
        except sqlite3.OperationalError:      # pragma: no cover
            pass
    try:
        row = await _fetchone(
            db,
            "SELECT COUNT(*) AS n FROM mca_source_refs "
            "WHERE chat_id = ? AND entity_id = ?",
            (int(chat_id), str(node.node_id)))
        impact["source_refs"] = int(_col(row, "n", 0) or 0)
    except sqlite3.OperationalError:      # pragma: no cover — до v17
        pass
    return impact


@dataclasses.dataclass(frozen=True)
class DuplicatePair:
    """Пара «member → canonical» с доказательством и влиянием на ссылки."""

    chat_id: int
    entity_type: str
    member_node_id: int
    canonical_node_id: int
    member_name: str
    canonical_name: str
    reasons: tuple[str, ...]
    verdict: str
    reason_code: str
    member_uids: tuple[int, ...]
    canonical_uids: tuple[int, ...]
    shared_uids: tuple[int, ...]
    impact: dict

    @property
    def safe(self) -> bool:
        return self.verdict == PAIR_SAFE

    @property
    def stable_identity(self) -> dict | None:
        """Единственное общее доказательство uid (для `apply_merge`)."""
        if len(self.shared_uids) != 1:
            return None
        return {"kind": er.STABLE_KIND_TG_USER, "value": int(self.shared_uids[0])}

    def key(self) -> str:
        return (f"{self.chat_id}:{self.entity_type}:"
                f"{self.member_node_id}->{self.canonical_node_id}")

    def as_dict(self) -> dict:
        return {
            "chat_id": self.chat_id, "entity_type": self.entity_type,
            "member_node_id": self.member_node_id,
            "canonical_node_id": self.canonical_node_id,
            "member_name": self.member_name,
            "canonical_name": self.canonical_name,
            "reasons": list(self.reasons), "verdict": self.verdict,
            "reason_code": self.reason_code, "safe": self.safe,
            "member_uids": list(self.member_uids),
            "canonical_uids": list(self.canonical_uids),
            "shared_uids": list(self.shared_uids),
            "impact": dict(self.impact),
        }


@dataclasses.dataclass(frozen=True)
class DuplicateReport:
    """Результат dry-run (B1): только факты, ноль записей."""

    chat_id: int
    entity_type: str
    dry_run: bool
    pairs: tuple[DuplicatePair, ...]
    totals: dict
    truncated: bool

    def safe_pairs(self) -> tuple[DuplicatePair, ...]:
        return tuple(pair for pair in self.pairs if pair.safe)

    def as_dict(self) -> dict:
        return {
            "chat_id": self.chat_id, "entity_type": self.entity_type,
            "dry_run": self.dry_run, "totals": dict(self.totals),
            "truncated": self.truncated,
            "pairs": [pair.as_dict()
                      for pair in self.pairs[:MAX_PAIR_PREVIEW]],
        }


def _classify_pair(chat_id: int, entity_type: str, member: _Node,
                   canonical: _Node, evidence: _IdentityEvidence,
                   member_impact: dict, canonical_impact: dict,
                   *, shared_sources: bool) -> DuplicatePair:
    """Вердикт пары: слияние доказывается ТОЛЬКО устойчивой идентичностью."""
    member_uids = evidence.uids(member.node_id)
    canonical_uids = evidence.uids(canonical.node_id)
    shared = tuple(sorted(set(member_uids) & set(canonical_uids)))
    reasons = [REASON_SAME_FOLDED_NAME]
    if shared:
        reasons.append(REASON_STABLE_IDENTITY)
    if shared_sources:
        reasons.append(REASON_SOURCE_OVERLAP)

    if not shared:
        verdict, reason_code = PAIR_REFUSED, REASON_IDENTITY_NOT_PROVEN
    elif len(member_uids) > 1 or len(canonical_uids) > 1:
        # ≥2 uid с одинаковым написанием — дефект данных, автовыбор запрещён.
        verdict, reason_code = PAIR_AMBIGUOUS, REASON_IDENTITY_AMBIGUOUS
    else:
        foreign = ((set(evidence.claims(member.node_id))
                    | set(evidence.claims(canonical.node_id))) - set(shared))
        if foreign:
            verdict, reason_code = (PAIR_AMBIGUOUS,
                                    REASON_IDENTITY_PINNED_ELSEWHERE)
        else:
            verdict, reason_code = PAIR_SAFE, REASON_STABLE_IDENTITY

    impact = {
        "edges": member_impact.get("edges", 0)
        + canonical_impact.get("edges", 0),
        "facts": member_impact.get("facts", 0)
        + canonical_impact.get("facts", 0),
        "target_user_facts": member_impact.get("target_user_facts", 0)
        + canonical_impact.get("target_user_facts", 0),
        "source_refs": member_impact.get("source_refs", 0)
        + canonical_impact.get("source_refs", 0),
    }
    return DuplicatePair(
        chat_id=int(chat_id), entity_type=str(entity_type),
        member_node_id=member.node_id,
        canonical_node_id=canonical.node_id,
        member_name=member.entity_name, canonical_name=canonical.entity_name,
        reasons=tuple(reasons), verdict=verdict, reason_code=reason_code,
        member_uids=member_uids, canonical_uids=canonical_uids,
        shared_uids=shared, impact=impact)


def _choose_canonical(first: _Node, second: _Node,
                      evidence: _IdentityEvidence) -> tuple[_Node, _Node]:
    """Кто остаётся каноническим. Детерминированно (§1.8, повтор = тот же отчёт).

    1) узел с активной self-строкой (доказан засевом) остаётся каноническим;
    2) иначе — меньший `nodes.id` (самый старый, на него ссылается история).
    """
    first_self = first.node_id in evidence.node_redirections \
        and evidence.node_redirections[first.node_id] == first.node_id
    second_self = second.node_id in evidence.node_redirections \
        and evidence.node_redirections[second.node_id] == second.node_id
    if first_self != second_self:
        return (first, second) if first_self else (second, first)
    return (first, second) if first.node_id < second.node_id else (second, first)


async def find_duplicate_candidates(
        db, chat_id: int, entity_type: str = "user", *,
        max_pairs: int = MAX_PAIRS_PER_CHAT,
        max_nodes: int = MAX_NODES_SCAN) -> DuplicateReport:
    """B1: dry-run кандидатов дублей чата/типа. **Ничего не пишет** (ID-1).

    Группировка — по `casefold(NFC(trim(name)))` (написание = причина показать
    пару, НЕ доказательство, ID-4). Внутри группы — пары с доказательством uid
    (`author_name` + alias-каскад) и влиянием на рёбра/факты/источники.
    Сходство эмбеддингов не вычисляется и не используется.
    """
    chat_id = int(chat_id)
    entity_type = str(entity_type)
    nodes, nodes_truncated = await _chat_nodes(
        db, chat_id, entity_type, limit=int(max_nodes))

    groups: dict[str, list[_Node]] = {}
    for node in nodes:
        groups.setdefault(_fold(node.entity_name), []).append(node)
    duplicate_groups = {key: value for key, value in groups.items()
                        if len(value) > 1}

    candidate_nodes = [node for value in duplicate_groups.values()
                       for node in value]
    evidence = await _collect_identity_evidence(
        db, chat_id, entity_type, candidate_nodes)
    # Узел, уже сведённый явной строкой, — не кандидат, а готовый redirect
    # (§1.4): повторный прогон не предлагает уже выполненные слияния.
    duplicate_groups = {
        key: [node for node in value
              if evidence.terminal(node.node_id) == node.node_id]
        for key, value in duplicate_groups.items()}
    duplicate_groups = {key: value for key, value in duplicate_groups.items()
                        if len(value) > 1}

    pairs: list[DuplicatePair] = []
    impact_cache: dict[int, dict] = {}
    source_buckets = await _source_buckets(db, chat_id) if duplicate_groups else {}
    truncated = bool(nodes_truncated or evidence.truncated)
    for key in sorted(duplicate_groups):
        group = sorted(duplicate_groups[key], key=lambda n: n.node_id)
        group_pairs = 0
        for i, first in enumerate(group):
            for second in group[i + 1:]:
                if len(pairs) >= max_pairs or \
                        group_pairs >= MAX_PAIRS_PER_GROUP:
                    truncated = True
                    break
                if evidence.redirect(second.node_id) == first.node_id or \
                        evidence.redirect(first.node_id) == second.node_id:
                    # Уже слиты явной строкой — не кандидат (идемпотентность).
                    continue
                canonical, member = _choose_canonical(first, second, evidence)
                for node in (first, second):
                    if node.node_id not in impact_cache:
                        impact_cache[node.node_id] = await _node_impact(
                            db, chat_id, node, entity_type)
                shared_sources = _shares_source(source_buckets, first, second)
                pairs.append(_classify_pair(
                    chat_id, entity_type, member, canonical, evidence,
                    impact_cache[first.node_id], impact_cache[second.node_id],
                    shared_sources=shared_sources))
                group_pairs += 1
            if len(pairs) >= max_pairs:
                truncated = True
                break
        if len(pairs) >= max_pairs:
            break

    pairs.sort(key=lambda pair: (pair.canonical_name, pair.member_node_id))
    totals = {
        "nodes_scanned": len(nodes),
        "duplicate_groups": len(duplicate_groups),
        "candidate_pairs": len(pairs),
        "safe": sum(1 for pair in pairs if pair.verdict == PAIR_SAFE),
        "ambiguous": sum(1 for pair in pairs
                         if pair.verdict == PAIR_AMBIGUOUS),
        "refused": sum(1 for pair in pairs if pair.verdict == PAIR_REFUSED),
        "edges_affected": sum(pair.impact.get("edges", 0) for pair in pairs),
        "facts_affected": sum(pair.impact.get("facts", 0) for pair in pairs),
        "source_refs_affected": sum(pair.impact.get("source_refs", 0)
                                    for pair in pairs),
    }
    _emit("memory.identity_duplicates_dry_run", chat_id=chat_id,
          status=REASON_DRY_RUN, counts=totals)
    return DuplicateReport(chat_id=chat_id, entity_type=entity_type,
                           dry_run=True, pairs=tuple(pairs), totals=totals,
                           truncated=truncated)


# ── применение слияния (B2) ────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class MergeResult:
    status: str
    reason_code: str
    chat_id: int
    entity_type: str
    member_node_id: int
    canonical_node_id: int
    legacy_id: int
    canonical_id: int
    detail: dict

    @property
    def applied(self) -> bool:
        return self.status in (REASON_MERGED, REASON_ALREADY_MERGED)

    def as_dict(self) -> dict:
        return {
            "status": self.status, "reason_code": self.reason_code,
            "chat_id": self.chat_id, "entity_type": self.entity_type,
            "member_node_id": self.member_node_id,
            "canonical_node_id": self.canonical_node_id,
            "legacy_id": self.legacy_id, "canonical_id": self.canonical_id,
            "detail": dict(self.detail),
        }


def _refusal(reason: str, chat_id: int, entity_type: str, member: int,
             canonical: int, detail: dict | None = None) -> MergeResult:
    return MergeResult(status=PAIR_REFUSED, reason_code=reason,
                       chat_id=int(chat_id), entity_type=str(entity_type),
                       member_node_id=int(member),
                       canonical_node_id=int(canonical),
                       legacy_id=int(member), canonical_id=int(canonical),
                       detail=dict(detail or {}))


async def _node_row(db, node_id: int):
    return await _fetchone(
        db, "SELECT id, chat_id, entity_name, entity_type FROM nodes "
            "WHERE id = ?", (int(node_id),))


async def validate_merge(db, chat_id: int, entity_type: str,
                         member_node_id: int, canonical_node_id: int, *,
                         stable_identity: Any = None) -> tuple[str, dict]:
    """Проверки §1.2.1/§1.4.2 перед записью redirect-строки.

    Возвращает `(reason_code, detail)`; пустой `reason_code` = можно писать.
    """
    member_id, canonical_id = int(member_node_id), int(canonical_node_id)
    chat_id, entity_type = int(chat_id), str(entity_type)
    if member_id == canonical_id:
        return REASON_SAME_NODE, {}
    member = await _node_row(db, member_id)
    canonical = await _node_row(db, canonical_id)
    if member is None or canonical is None:
        return REASON_NODE_MISSING, {"member": member is not None,
                                     "canonical": canonical is not None}
    for row in (member, canonical):
        if int(_col(row, "chat_id", 1)) != chat_id:
            return REASON_NODE_MISSING, {"foreign_chat": True}
        if str(_col(row, "entity_type", 3)) != entity_type:
            return REASON_TYPE_CONFLICT, {
                "node_type": str(_col(row, "entity_type", 3))}

    # §1.4.2: глубина 1 терминальна, автоматического «выпрямления» нет.
    # В `by_member` попадают ТОЛЬКО настоящие redirect-строки
    # (`member != canonical`): self-строка засева (§1.2.1) — не редирект, иначе
    # засеянный канонический узел ошибочно считался бы «уже сведённым» и
    # слияние второго написания молча отказывало. Закрепление uid проверяется
    # отдельно (claims ниже) — precise refusal не ослаблен.
    active = await _active_merge_rows(db, chat_id, entity_type)
    by_member = {
        int(_col(row, "member_node_id", 0)): int(_col(row, "canonical_node_id", 1))
        for row in active
        if int(_col(row, "member_node_id", 0))
        != int(_col(row, "canonical_node_id", 1))
    }
    if canonical_id in by_member:
        target = by_member[canonical_id]
        return (REASON_REDIRECT_CYCLE if target == member_id
                else REASON_REDIRECT_CHAIN), {"canonical_is_member": True}
    if any(value == member_id for value in by_member.values()):
        return REASON_REDIRECT_CHAIN, {"member_is_canonical": True}
    existing = by_member.get(member_id)
    if existing is not None:
        if existing == canonical_id:
            return REASON_ALREADY_MERGED, {}
        return REASON_MERGE_CONFLICT, {"current_canonical": existing}

    uid = er.parse_stable_identity(stable_identity)   # один разбор, один владелец
    if uid is None:
        return REASON_IDENTITY_NOT_PROVEN, {"stable_identity": False}
    evidence = await _collect_identity_evidence(
        db, chat_id, entity_type,
        [_Node(member_id, str(_col(member, "entity_name", 2)), entity_type),
         _Node(canonical_id, str(_col(canonical, "entity_name", 2)),
               entity_type)])
    wanted = int(uid)
    for node_id in (member_id, canonical_id):
        uids = set(evidence.uids(node_id))
        if wanted not in uids:
            return REASON_IDENTITY_NOT_PROVEN, {"node_id": node_id}
        if len(uids) > 1:
            return REASON_IDENTITY_AMBIGUOUS, {"node_id": node_id}
        if set(evidence.claims(node_id)) - {wanted}:
            return REASON_IDENTITY_PINNED_ELSEWHERE, {"node_id": node_id}
    return "", {}


async def _uid_claim_rows(db, chat_id: int, entity_type: str, uid: str) -> list[Any]:
    """Активные строки, закрепляющие `uid` за узлом (member или canonical).

    Нужны, чтобы слияние не дублировало уже действующую идентичность: частичный
    `UNIQUE (chat_id, entity_type, stable_kind, stable_value) WHERE status='active'`
    (§5.1, ID-11) остаётся ровно как в схеме — второй активной строки с тем же
    uid не создаётся.
    """
    try:
        return await _fetchall(
            db,
            f"SELECT member_node_id, canonical_node_id FROM {MERGE_TABLE} "
            "WHERE chat_id = ? AND entity_type = ? AND stable_kind = ? "
            "AND stable_value = ? AND status = ?",
            (int(chat_id), str(entity_type), er.STABLE_KIND_TG_USER,
             str(uid), er.STATUS_ACTIVE),
        )
    except sqlite3.OperationalError:      # pragma: no cover — БД до v43
        return []


async def _merge_uid_columns(db, chat_id: int, entity_type: str,
                             member_node_id: int, canonical_node_id: int,
                             uid: str) -> tuple[str | None, str | None, str]:
    """Какие `stable_kind/stable_value` писать строке слияния.

    `(kind, value, refusal)`. Слияние — про НАПИСАНИЯ узлов, а не про новое
    закрепление uid: если идентичность уже активна (self-строка засева на
    каноническом узле — штатный случай), в строке `resolution='merged'`
    остаются `NULL`, иначе частичный `UNIQUE` дал бы конфликт. Если uid
    закреплён за ТРЕТЬИМ узлом, слияние отказывает — молча терять claim нельзя.
    """
    member_id, canonical_id = int(member_node_id), int(canonical_node_id)
    claims = await _uid_claim_rows(db, chat_id, entity_type, uid)
    if not claims:
        return er.STABLE_KIND_TG_USER, str(uid), ""
    row_members = {int(_col(row, "member_node_id", 0)) for row in claims}
    row_canonicals = {int(_col(row, "canonical_node_id", 1)) for row in claims}
    if canonical_id in row_canonicals or canonical_id in row_members:
        return None, None, ""
    if member_id in row_members:
        # Строка самого member уже держит uid — переиспользуется (тот же PK).
        return er.STABLE_KIND_TG_USER, str(uid), ""
    return None, None, REASON_IDENTITY_PINNED_ELSEWHERE


async def apply_merge(db, chat_id: int, entity_type: str,
                      member_node_id: int, canonical_node_id: int, *,
                      stable_identity: Any = None,
                      evidence_ref_id: int | None = None,
                      method: str = er.METHOD_EXPLICIT_EVIDENCE,
                      confidence: str = er.CONFIDENCE_CONFIRMED,
                      now: int | None = None) -> MergeResult:
    """B2: одно безопасное слияние — ОДНА аддитивная строка, транзакционно.

    Требует доказанной устойчивой идентичности (`stable_identity` + реальные
    данные): без неё — отказ, слияние не выполняется никогда. Идемпотентно по
    PK `(chat_id, entity_type, member_node_id)`; повтор — `already_merged`.
    """
    reason, detail = await validate_merge(
        db, chat_id, entity_type, member_node_id, canonical_node_id,
        stable_identity=stable_identity)
    if reason == REASON_ALREADY_MERGED:
        return MergeResult(status=REASON_ALREADY_MERGED,
                           reason_code=REASON_ALREADY_MERGED,
                           chat_id=int(chat_id), entity_type=str(entity_type),
                           member_node_id=int(member_node_id),
                           canonical_node_id=int(canonical_node_id),
                           legacy_id=int(member_node_id),
                           canonical_id=int(canonical_node_id),
                           detail=dict(detail))
    if reason:
        _emit("memory.identity_merge_refused", outcome="refused",
              chat_id=int(chat_id), status=reason,
              entity_ids=[int(member_node_id), int(canonical_node_id)])
        return _refusal(reason, chat_id, entity_type, member_node_id,
                        canonical_node_id, detail)

    stamp = int(now if now is not None else time.time())
    uid = er.parse_stable_identity(stable_identity)
    stable_kind, stable_value, claim_refusal = await _merge_uid_columns(
        db, chat_id, entity_type, member_node_id, canonical_node_id, uid)
    if claim_refusal:
        _emit("memory.identity_merge_refused", outcome="refused",
              chat_id=int(chat_id), status=claim_refusal,
              entity_ids=[int(member_node_id), int(canonical_node_id)])
        return _refusal(claim_refusal, chat_id, entity_type, member_node_id,
                        canonical_node_id, {"uid": str(uid)})

    existing = await _fetchone(
        db,
        f"SELECT canonical_node_id, status FROM {MERGE_TABLE} "
        "WHERE chat_id = ? AND entity_type = ? AND member_node_id = ?",
        (int(chat_id), str(entity_type), int(member_node_id)),
    )
    if existing is not None:
        # §1.4.2: ремонт отозванного слияния — ЯВНОЕ повторное слияние,
        # автоматического оживления нет. Строка переиспользуется (PK), аудит
        # `legacy_id → canonical_id` сохраняется.
        async def _reactivate(conn):
            await conn.execute(
                f"UPDATE {MERGE_TABLE} SET canonical_node_id = ?, "
                "resolution = ?, stable_kind = ?, stable_value = ?, "
                "method = ?, evidence_ref_id = ?, confidence = ?, status = ?, "
                "updated_at = ? WHERE chat_id = ? AND entity_type = ? "
                "AND member_node_id = ?",
                (int(canonical_node_id), er.RESOLUTION_MERGED,
                 stable_kind, stable_value,
                 str(method), evidence_ref_id, str(confidence),
                 er.STATUS_ACTIVE, stamp, int(chat_id), str(entity_type),
                 int(member_node_id)),
            )

        await db.write_transaction(
            _reactivate, op_name="entity_merge_reactivate",
            chat_id=int(chat_id))
        _emit("memory.identity_merge", chat_id=int(chat_id),
              status=REASON_MERGED,
              entity_ids=[int(member_node_id), int(canonical_node_id)])
        return MergeResult(status=REASON_MERGED, reason_code=REASON_MERGED,
                           chat_id=int(chat_id), entity_type=str(entity_type),
                           member_node_id=int(member_node_id),
                           canonical_node_id=int(canonical_node_id),
                           legacy_id=int(member_node_id),
                           canonical_id=int(canonical_node_id),
                           detail={"method": str(method),
                                   "confidence": str(confidence),
                                   "reactivated": True})

    async def _insert(conn):
        await conn.execute(
            f"INSERT INTO {MERGE_TABLE} ("
            "chat_id, entity_type, member_node_id, canonical_node_id, "
            "resolution, stable_kind, stable_value, method, evidence_ref_id, "
            "confidence, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (int(chat_id), str(entity_type), int(member_node_id),
             int(canonical_node_id), er.RESOLUTION_MERGED,
             stable_kind, stable_value, str(method),
             evidence_ref_id, str(confidence), er.STATUS_ACTIVE,
             stamp, stamp),
        )

    try:
        await db.write_transaction(_insert, op_name="entity_merge_apply",
                                   chat_id=int(chat_id))
    except sqlite3.IntegrityError as exc:
        # Параллельный прогон/частичный unique: строка уже есть — не перезапись.
        logger.info("[entity_merge] merge insert conflicted | chat=%s | %s",
                    chat_id, exc)
        current = await validate_merge(
            db, chat_id, entity_type, member_node_id, canonical_node_id,
            stable_identity=stable_identity)
        if current[0] == REASON_ALREADY_MERGED:
            return MergeResult(
                status=REASON_ALREADY_MERGED,
                reason_code=REASON_ALREADY_MERGED, chat_id=int(chat_id),
                entity_type=str(entity_type),
                member_node_id=int(member_node_id),
                canonical_node_id=int(canonical_node_id),
                legacy_id=int(member_node_id),
                canonical_id=int(canonical_node_id), detail={})
        return _refusal(current[0] or REASON_MERGE_CONFLICT, chat_id,
                        entity_type, member_node_id, canonical_node_id,
                        current[1])

    _emit("memory.identity_merge", chat_id=int(chat_id), status=REASON_MERGED,
          entity_ids=[int(member_node_id), int(canonical_node_id)])
    return MergeResult(status=REASON_MERGED, reason_code=REASON_MERGED,
                       chat_id=int(chat_id), entity_type=str(entity_type),
                       member_node_id=int(member_node_id),
                       canonical_node_id=int(canonical_node_id),
                       legacy_id=int(member_node_id),
                       canonical_id=int(canonical_node_id),
                       detail={"method": str(method),
                               "confidence": str(confidence)})


async def revoke_merge(db, chat_id: int, entity_type: str, member_node_id: int,
                       *, now: int | None = None) -> bool:
    """Откат слияния: `status='revoked'` (данные и аудит остаются)."""
    stamp = int(now if now is not None else time.time())
    changed = {"rows": 0}

    async def _body(conn):
        cursor = await conn.execute(
            f"UPDATE {MERGE_TABLE} SET status = ?, updated_at = ? "
            "WHERE chat_id = ? AND entity_type = ? AND member_node_id = ? "
            "AND status = ?",
            (er.STATUS_REVOKED, stamp, int(chat_id), str(entity_type),
             int(member_node_id), er.STATUS_ACTIVE))
        changed["rows"] = int(cursor.rowcount or 0)

    await db.write_transaction(_body, op_name="entity_merge_revoke",
                               chat_id=int(chat_id))
    if changed["rows"]:
        _emit("memory.identity_merge_revoked", chat_id=int(chat_id),
              status=REASON_REVOKED, entity_ids=[int(member_node_id)])
        return True
    return False


# ── агрегированное ребро после слияния (§2.5) ──────────────────────────────

@dataclasses.dataclass(frozen=True)
class AggregatedEdge:
    """Группа строк `edges`, схлопнутая на ЧТЕНИИ по канонической тройке."""

    chat_id: int
    source_id: int
    target_id: int
    relation_type: str
    edge_id: int
    legacy_edge_ids: tuple[int, ...]
    fact_ids: tuple[int, ...]
    weight: float
    source_ref_ids: tuple[int, ...]
    members: tuple[dict, ...]

    def as_dict(self) -> dict:
        return {
            "chat_id": self.chat_id, "source_id": self.source_id,
            "target_id": self.target_id, "relation_type": self.relation_type,
            "edge_id": self.edge_id, "legacy_edge_ids": list(self.legacy_edge_ids),
            "fact_ids": list(self.fact_ids), "weight": self.weight,
            "source_ref_ids": list(self.source_ref_ids),
            "members": [dict(member) for member in self.members],
        }


async def _canonical_map(db, chat_id: int) -> dict[int, int]:
    """`member_node_id → canonical_node_id` по активным строкам чата (§1.4).

    Глубина 1 терминальна (§1.4.2 проверяется на записи), но легаси/ручная
    правка может дать цепочку: читаем до последнего достижимого узла (bounded,
    с защитой от цикла). Данные при этом НЕ переписываются — «выпрямления» нет.
    """
    try:
        rows = await _fetchall(
            db,
            f"SELECT member_node_id, canonical_node_id FROM {MERGE_TABLE} "
            "WHERE chat_id = ? AND status = ?",
            (int(chat_id), er.STATUS_ACTIVE))
    except sqlite3.OperationalError:      # pragma: no cover — до v43
        return {}
    raw = {int(_col(row, "member_node_id", 0)):
           int(_col(row, "canonical_node_id", 1)) for row in rows}
    resolved: dict[int, int] = {}
    for member in raw:
        current = raw[member]
        visited = {member}
        steps = 0
        while steps < 8:
            nxt = raw.get(current)
            if nxt is None or nxt == current or nxt in visited:
                break
            visited.add(nxt)
            current = nxt
            steps += 1
        resolved[member] = current
    return resolved


async def aggregate_edges(db, chat_id: int, *, source_id: int | None = None,
                          target_id: int | None = None,
                          limit: int = 500) -> list[AggregatedEdge]:
    """§2.5: одно смысловое ребро из нескольких строк после слияния узлов.

    `edge_id` = минимальный `edges.id` группы (детерминированно), остальные —
    `legacy_edge_ids`; `fact_ids`/`source_ref_ids` — объединение оснований,
    ни один `fact_id` не теряется; строки не удаляются и не переписываются.
    """
    chat_id = int(chat_id)
    canonical = await _canonical_map(db, chat_id)
    members_for: dict[int, list[int]] = {}
    for member, target in canonical.items():
        members_for.setdefault(target, []).append(member)

    def canonical_of(node_id: int) -> int:
        return int(canonical.get(int(node_id), int(node_id)))

    def ids_for(node_id: int) -> list[int]:
        root = canonical_of(node_id)
        return sorted(set([root, *members_for.get(root, [])]))

    sql = ("SELECT id, source_id, target_id, relation_type, weight, "
           "expires_at, origin, fact_id FROM edges WHERE chat_id = ?")
    params: list[Any] = [chat_id]
    if source_id is not None:
        bucket = ids_for(source_id)
        sql += f" AND source_id IN ({', '.join('?' for _ in bucket)})"
        params.extend(bucket)
    if target_id is not None:
        bucket = ids_for(target_id)
        sql += f" AND target_id IN ({', '.join('?' for _ in bucket)})"
        params.extend(bucket)
    sql += " ORDER BY id LIMIT ?"
    params.append(int(limit))

    rows = await _fetchall(db, sql, params)
    groups: dict[tuple[int, int, str], list[Any]] = {}
    for row in rows:
        key = (canonical_of(_col(row, "source_id", 1)),
               canonical_of(_col(row, "target_id", 2)),
               str(_col(row, "relation_type", 3)))
        groups.setdefault(key, []).append(row)

    edge_refs = await _edge_source_refs(db, chat_id)
    aggregates: list[AggregatedEdge] = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda row: int(_col(row, "id", 0)))
        edge_ids = [int(_col(row, "id", 0)) for row in group]
        fact_ids = sorted({int(_col(row, "fact_id", 7))
                           for row in group
                           if _col(row, "fact_id", 7) is not None})
        refs: set[int] = set()
        for edge_id in edge_ids:
            refs |= edge_refs.get(edge_id, set())
        members = tuple({
            "edge_id": int(_col(row, "id", 0)),
            "source_id": int(_col(row, "source_id", 1)),
            "target_id": int(_col(row, "target_id", 2)),
            "weight": float(_col(row, "weight", 4) or 0.0),
            "expires_at": _col(row, "expires_at", 5),
            "origin": _col(row, "origin", 6),
            "fact_id": (_col(row, "fact_id", 7)
                        if _col(row, "fact_id", 7) is None
                        else int(_col(row, "fact_id", 7))),
        } for row in group)
        aggregates.append(AggregatedEdge(
            chat_id=chat_id, source_id=key[0], target_id=key[1],
            relation_type=key[2], edge_id=edge_ids[0],
            legacy_edge_ids=tuple(edge_ids[1:]),
            fact_ids=tuple(fact_ids),
            weight=sum(float(_col(row, "weight", 4) or 0.0) for row in group),
            source_ref_ids=tuple(sorted(refs)), members=members))
    aggregates.sort(key=lambda item: item.edge_id)
    return aggregates


async def _edge_source_refs(db, chat_id: int) -> dict[int, set[int]]:
    """`edges.id → {source_ref_id}` из типизированных edge-ссылок (§2.5).

    Читаются ТОЛЬКО существующие строки: до MEMORY-03 edge-ссылок нет →
    пустая карта (объединение оснований тогда видно по `fact_ids`), выдуманных
    источников не появляется.
    """
    try:
        rows = await _fetchall(
            db,
            "SELECT r.entity_id AS entity_id, l.source_ref_id AS source_ref_id "
            "FROM mca_source_refs r "
            "JOIN mca_evidence_links l ON l.subject_ref_id = r.source_ref_id "
            "WHERE r.chat_id = ? AND r.entity_type = 'graph_edge'",
            (int(chat_id),))
    except sqlite3.OperationalError:      # pragma: no cover — до v17
        return {}
    result: dict[int, set[int]] = {}
    for row in rows:
        try:
            edge_id = int(str(_col(row, "entity_id", 0)))
        except (TypeError, ValueError):   # pragma: no cover — мусорная строка
            continue
        result.setdefault(edge_id, set()).add(int(_col(row, "source_ref_id", 1)))
    return result


# ── чекпоинт (durable-носитель — существующая `task_jobs`, §5.3) ───────────

class InMemoryCheckpoint:
    """Чекпоинт в памяти (тесты/одиночный прогон). Интерфейс `load`/`save`."""

    def __init__(self, state: dict | None = None) -> None:
        self.state = dict(state or {})

    async def load(self) -> dict:
        return dict(self.state)

    async def save(self, state: dict) -> None:
        self.state = dict(state)


class TaskJobsCheckpoint:
    """Durable-чекпоинт в `task_jobs.payload` (новой таблицы не создаётся).

    Строка терминальная (`status='completed'`), поэтому супервайзер не
    подбирает её как работу — тот же приём, что `intent_heartbeat_liveness`.
    """

    def __init__(self, db, job_id: str = MERGE_JOB_ID) -> None:
        self.db = db
        self.job_id = str(job_id)

    async def load(self) -> dict:
        try:
            row = await _fetchone(
                self.db, "SELECT payload FROM task_jobs WHERE job_id = ?",
                (self.job_id,))
        except sqlite3.OperationalError:      # pragma: no cover
            return {}
        if row is None:
            return {}
        try:
            data = json.loads(_col(row, "payload", 0) or "{}")
        except Exception:      # pragma: no cover — битый payload
            return {}
        return data if isinstance(data, dict) else {}

    async def save(self, state: dict) -> None:
        payload = json.dumps(state, ensure_ascii=False)
        stamp = int(time.time())

        async def _body(conn):
            await conn.execute(
                "INSERT INTO task_jobs (job_id, owner, kind, status, payload, "
                "attempt, max_attempts, created_at, updated_at, heartbeat_at, "
                "finished_at) VALUES (?, ?, ?, 'completed', ?, 0, 1, ?, ?, ?, ?) "
                "ON CONFLICT(job_id) DO UPDATE SET payload = excluded.payload, "
                "updated_at = excluded.updated_at, "
                "heartbeat_at = excluded.heartbeat_at",
                (self.job_id, MERGE_JOB_OWNER, MERGE_JOB_KIND, payload,
                 stamp, stamp, stamp, stamp))

        await self.db.write_transaction(_body, op_name="entity_merge_checkpoint")


def _empty_state(entity_type: str) -> dict:
    return {"version": 1, "entity_type": str(entity_type),
            "processed": [], "chats_done": [], "applied": 0,
            "updated_at": 0}


async def run_merge_backfill(
        db, *, chat_id: int | None = None, entity_type: str = "user",
        dry_run: bool = True, checkpoint=None, max_pairs: int = MAX_PAIRS_PER_CHAT,
        max_chats: int | None = None, now: int | None = None,
        require_gate: bool = True) -> dict:
    """B1/B2: прогон по чатам с чекпоинтом и честным resume.

    `dry_run=True` — только отчёт (ноль записей). `dry_run=False` — применяются
    ТОЛЬКО пары с доказанной устойчивой идентичностью; каждая — отдельной
    транзакцией; после чата чекпоинт сохраняется, повторный запуск продолжает
    с места остановки (`resumed_skips`), не переприменяя слияния.
    """
    stamp = int(now if now is not None else time.time())
    entity_type = str(entity_type)
    state = _empty_state(entity_type)
    if checkpoint is not None:
        loaded = await checkpoint.load()
        if isinstance(loaded, dict) and loaded:
            state["processed"] = list(loaded.get("processed") or [])
            state["chats_done"] = list(loaded.get("chats_done") or [])
            state["applied"] = int(loaded.get("applied") or 0)
    processed = set(state["processed"])

    if chat_id is not None:
        chats = [int(chat_id)]
    else:
        rows = await _fetchall(
            db,
            "SELECT DISTINCT chat_id FROM nodes WHERE entity_type = ? "
            "ORDER BY chat_id",
            (entity_type,))
        chats = [int(_col(row, "chat_id", 0)) for row in rows]
    if max_chats is not None:
        chats = chats[:int(max_chats)]

    summary = {
        "dry_run": bool(dry_run), "entity_type": entity_type,
        "chats": len(chats), "candidate_pairs": 0, "safe_pairs": 0,
        "ambiguous_pairs": 0, "refused_pairs": 0, "attempted_pairs": 0,
        "applied": 0, "already_merged": 0, "resumed_skips": 0,
        "gate_off": 0, "errors": 0, "truncated": False,
        "reports": [],
    }

    for current_chat in chats:
        if not dry_run and require_gate and \
                not await mca_gates.memory_identity_enabled(current_chat):
            summary["gate_off"] += 1
            continue
        report = await find_duplicate_candidates(
            db, current_chat, entity_type, max_pairs=max_pairs)
        summary["candidate_pairs"] += report.totals["candidate_pairs"]
        summary["safe_pairs"] += report.totals["safe"]
        summary["ambiguous_pairs"] += report.totals["ambiguous"]
        summary["refused_pairs"] += report.totals["refused"]
        summary["truncated"] = summary["truncated"] or report.truncated
        summary["reports"].append(report.as_dict())
        if dry_run:
            continue
        for pair in report.safe_pairs():
            key = pair.key()
            if key in processed:
                summary["resumed_skips"] += 1
                continue
            summary["attempted_pairs"] += 1
            try:
                result = await apply_merge(
                    db, pair.chat_id, pair.entity_type,
                    pair.member_node_id, pair.canonical_node_id,
                    stable_identity=pair.stable_identity, now=stamp)
            except Exception:
                summary["errors"] += 1
                logger.warning("[entity_merge] backfill apply failed | %s",
                               key, exc_info=True)
                continue
            if result.status == REASON_MERGED:
                summary["applied"] += 1
                state["applied"] = int(state["applied"]) + 1
            elif result.status == REASON_ALREADY_MERGED:
                summary["already_merged"] += 1
            processed.add(key)
            state["processed"] = sorted(processed)
        state["chats_done"] = sorted(set(state["chats_done"]) | {current_chat})
        state["updated_at"] = stamp
        if checkpoint is not None:
            await checkpoint.save(state)

    return summary


__all__ = [
    "MERGE_TABLE", "MERGE_JOB_ID",
    "REASON_SAME_FOLDED_NAME", "REASON_STABLE_IDENTITY",
    "REASON_SOURCE_OVERLAP", "REASON_IDENTITY_NOT_PROVEN",
    "REASON_IDENTITY_AMBIGUOUS", "REASON_IDENTITY_PINNED_ELSEWHERE",
    "REASON_NODE_MISSING", "REASON_TYPE_CONFLICT", "REASON_SAME_NODE",
    "REASON_REDIRECT_CHAIN", "REASON_REDIRECT_CYCLE", "REASON_ALREADY_MERGED",
    "REASON_MERGE_CONFLICT", "REASON_MERGED", "REASON_REVOKED",
    "REASON_GATE_OFF", "PAIR_SAFE", "PAIR_AMBIGUOUS", "PAIR_REFUSED",
    "DuplicatePair", "DuplicateReport", "find_duplicate_candidates",
    "MergeResult", "validate_merge", "apply_merge", "revoke_merge",
    "AggregatedEdge", "aggregate_edges",
    "InMemoryCheckpoint", "TaskJobsCheckpoint", "run_merge_backfill",
]
