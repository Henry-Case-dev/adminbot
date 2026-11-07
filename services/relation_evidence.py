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
  * класс происхождения основания выводится по атрибуции САМОГО ФАКТА
    (`perspective`/`attribution_method`/`forward_from` живут в `graph_facts`):
    пересказ третьего лица — `reported_third_party`, репост/цитата —
    `quote_forward`; ни то, ни другое не создаёт независимый корень
    (MEM-03.4, §2.2/§2.3, R-4/§2.8). `method='direct_reference'` ставится
    только прямому утверждению автора;
  * собственный вывод бота (`origin='bot_self_reply'|'bot_direct_reply'`,
    `provenance.is_self_referential_origin`) опирается на собственную строку
    факта с `independence='self_referential'` и в независимую поддержку не
    входит (R-3); сообщение человека источником реплики бота не объявляется;
  * транзитивность не выводится (R-5): `A–B` и `B–C` не дают `A–C`;
  * ревизия SourceRef ребра — константа (`'stable'`): повторная обработка того
    же сообщения/ребра не создаёт второй SourceRef и не раздувает
    `independent_support` (R-13, §2.4.1);
  * чтение объединяет ВСЕ ревизии SourceRef'ов ребра (§2.4.2) — «только самая
    свежая ревизия» запрещено;
  * счётчик независимых корней — один на проект
    (`provenance.evidence_independent_count`), поэтому слой данных и контракт
    (`RelationView.independent_support`) не могут разойтись.

Когда корень нельзя установить честно (нет адреса первоисточника, нет
сохранённого сообщения автора), основание пишется как `tentative`/`unknown` и
НЕ считается подтверждением: лучше меньше независимости, чем выдуманная.

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
    AssertionMode,
    OriginClass,
    RelationSourceView,
    RelationStatus,
    RelationView,
    resolve_assertion_mode,
)
from services.graphrag_provenance import (
    ORIGIN_COOCCURRENCE,
    ORIGIN_DERIVED_WITH_LINEAGE,
    ORIGIN_EXPLICIT_DIRECT,
    ORIGIN_LEGACY_UNKNOWN,
    ORIGIN_QUOTE_FORWARD,
    ORIGIN_REPORTED_THIRD_PARTY,
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

# ── §2.3: что класс происхождения позволяет утверждать о ребре ──────────────
# План записи основания. `root` — от чего адресуется основание:
#   * `message` — сохранённое сообщение автора (только прямое утверждение);
#   * `fact`    — строка `graph_facts`, из которой выведено ребро.
# Атрибуция (perspective/attribution_method/forward_from) живёт в `graph_facts`,
# поэтому по ней и решается класс: пересказ, репост и производное НЕ становятся
# независимым корнем (MEM-03.4, §2.2/§2.3, §2.8). Метод `direct_reference`
# ставится только прямому утверждению автора — приписывать его пересказу
# запрещено.
_EVIDENCE_PLANS: dict[str, dict] = {
    ORIGIN_EXPLICIT_DIRECT: {
        "root": "message", "link_type": "supports",
        "verification": "verified", "independence": "independent",
        "method": "direct_reference",
        "basis": "прямое утверждение автора в сохранённом сообщении",
    },
    ORIGIN_REPORTED_THIRD_PARTY: {
        "root": "fact", "link_type": "derived_from",
        "verification": "tentative", "independence": "unknown",
        "method": "metadata",
        "basis": "пересказ третьего лица — первоисточник не установлен",
    },
    ORIGIN_QUOTE_FORWARD: {
        "root": "message", "link_type": "derived_from",
        "verification": "tentative", "independence": "unknown",
        "method": "metadata",
        "basis": "forward",
    },
    ORIGIN_DERIVED_WITH_LINEAGE: {
        "root": "fact", "link_type": "derived_from",
        "verification": "tentative", "independence": "unknown",
        "method": "metadata",
        "basis": "производное с цепочкой, не прямое утверждение",
    },
    ORIGIN_COOCCURRENCE: {
        "root": "fact", "link_type": "mentions",
        "verification": "unknown", "independence": "unknown",
        "method": "metadata",
        "basis": "только упоминание, не утверждение",
    },
    ORIGIN_LEGACY_UNKNOWN: {
        "root": "fact", "link_type": "derived_from",
        "verification": "unknown", "independence": "unknown",
        "method": "unknown",
        "basis": "происхождение не установлено",
    },
}

# R-3: собственный вывод бота. Основание — его же записанный факт, никогда
# сообщение человека (иначе реплика бота выдаётся за слова спрашивающего).
_BOT_SELF_PLAN = {
    "root": "fact", "link_type": "derived_from",
    "verification": "tentative", "independence": "self_referential",
    "method": "metadata",
    "basis": "собственный вывод бота — не подтверждение человека",
}

# `world_knowledge`: автор говорит о мире, не о человеке. Это НЕ подтверждение
# авторства личной связи (§2.3/MEM-03.3). Класс `derived_with_lineage`:
# lineage — сообщение автора; запись `tentative`/`unknown`, независимым
# корнем не становится. Нет адреса сообщения — lineage не разрешён, и тогда
# честно `legacy_unknown` (`_EVIDENCE_PLANS[ORIGIN_LEGACY_UNKNOWN]`).
_WORLD_KNOWLEDGE_PLAN = {
    "root": "message", "link_type": "derived_from",
    "verification": "tentative", "independence": "unknown",
    "method": "metadata",
    "basis": "общие знания (world_knowledge) — не подтверждение о человеке",
}

# Класс без адресуемого сообщения автора: независимость не заявляется.
_NO_ADDRESS_PLAN = {
    "root": "fact", "link_type": "supports",
    "verification": "tentative", "independence": "unknown",
    "method": "metadata",
    "basis": "утверждение без сохранённого адреса источника",
}


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
        link_type: str = "derived_from", method: str = "unknown",
        verification: str = "unknown", independence: str = "unknown",
        claim_key: str | None = None, basis: str | None = None,
        established_at: int = 0,
        extractor_version: str | None = None) -> int | None:
    """Привязать источник к ребру (идемпотентно по UNIQUE-индексу links).

    Дефолты — БЕЗОПАСНЫЕ: `derived_from` + `unknown`/`unknown`, ни подтверждения,
    ни независимости по умолчанию не заявляется (F2). Все осмысленные значения
    приходят от политики (`attach_fact_edge_evidence`) или явного вызывающего.

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


async def _load_fact_row(db, chat_id: int, fact_id) -> dict:
    """Строка факта: в ней живёт атрибуция (perspective/attribution/forward)."""
    try:
        cursor = await db.db.execute(
            "SELECT id, chat_id, origin, perspective, attribution_method, "
            "provenance_channel, forward_from, subject_ref_id, tg_message_id, "
            "subject_entity_id, target_user, speaker_author_id, assertion_kind "
            "FROM graph_facts WHERE id = ? AND chat_id = ?",
            (int(fact_id), int(chat_id)))
        row = await cursor.fetchone()
    except Exception:
        logger.warning("[relation_evidence] fact row read failed | fact_id=%s",
                       fact_id, exc_info=True)
        return {}
    return dict(row) if row is not None else {}


async def _load_author_message(db, chat_id, tg_message_id) -> dict:
    """Сохранённое сообщение по `(chat, tg_message_id)` — только чтение.

    Это второй реальный сигнал авторства: если сообщения нет, подтверждать
    авторство нечем (fail-open → `legacy_unknown`).
    """
    if chat_id is None or tg_message_id is None:
        return {}
    try:
        cursor = await db.db.execute(
            "SELECT id, user_id, author_name, is_forward, forward_source "
            "FROM smart_messages WHERE chat_id = ? AND tg_message_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (int(chat_id), int(tg_message_id)))
        row = await cursor.fetchone()
    except Exception:                                     # pragma: no cover
        return {}
    return dict(row) if row is not None else {}


def _message_forwarded(msg: dict) -> bool:
    """Сохранённое сообщение — репост/цитата (§2.2.1(г))."""
    return bool(msg) and (
        bool(msg.get("is_forward"))
        or bool(str(msg.get("forward_source") or "").strip()))


def _uid_from_ref(ref: dict | None) -> int | None:
    """`user`-SourceRef → устойчивый uid; неразрешённый адрес — не uid."""
    if not ref:
        return None
    if str(ref.get("entity_type") or "") != "user":
        return None
    if str(ref.get("resolution") or "") != "resolved":
        return None
    try:
        return int(str(ref.get("entity_id")))
    except (TypeError, ValueError):
        return None


async def _subject_uids(db, row: dict, *, subject=None,
                        target_user=None,
                        speaker_author_id=None) -> set[int]:
    """Устойчивые uid субъекта/говорящего факта (§2.2.1, пункт 2).

    Только идентичности, разрешённые однозначно:
      * `speaker_author_id` — говорящий (достаточен сам по себе);
      * `subject_ref_id` → `user`-SourceRef с `resolution='resolved'`;
      * `target_user`/`subject`, разрешённые ровно в один uid
        (`provenance.resolve_subject_ref`; при 0 или ≥2 одноимённых —
        **не** совпадение, §2.2.1(е)).
    Сравнения по отображаемому имени нет вовсе.
    """
    uids: set[int] = set()
    speaker_id = speaker_author_id or row.get("speaker_author_id")
    if speaker_id is not None:
        try:
            uids.add(int(speaker_id))
        except (TypeError, ValueError):
            pass
    ref_id = row.get("subject_ref_id")
    if ref_id is not None:
        uid = _uid_from_ref(await provenance.get_source_ref(db, int(ref_id)))
        if uid is not None:
            uids.add(uid)
    chat_id = row.get("chat_id")
    for name in (target_user, row.get("target_user"), subject):
        cleaned = str(name or "").strip()
        if not cleaned or chat_id is None:
            continue
        try:
            ref = await provenance.resolve_subject_ref(db, chat_id, cleaned)
        except Exception:                                 # pragma: no cover
            continue
        if ref.resolution != "resolved":
            continue          # 0 или ≥2 одноимённых → не совпадение (п. «е»)
        uid = _uid_from_ref(ref.as_dict())
        if uid is not None:
            uids.add(uid)
    return uids


async def _authorship_corroborated(db, row: dict, *, subject=None,
                                   target_user=None,
                                   speaker_author_id=None) -> bool:
    """Подтверждено ли авторство факта сохранённым сообщением (§2.2.1).

    Условия (все обязательны):
      * сообщение реально есть в этом чате по `tg_message_id`;
      * сообщение не является репостом/цитатой (это `quote_forward`, п. «г»);
      * `smart_messages.user_id` совпадает с устойчивым uid субъекта/говорящего
        факта. Одноимённость (≥2 uid) совпадением НЕ считается (п. «е»).
    """
    msg = await _load_author_message(
        db, row.get("chat_id"), row.get("tg_message_id"))
    if not msg or _message_forwarded(msg):
        return False
    author_id = msg.get("user_id")
    if author_id is None:
        return False                # автора без uid отождествить нечем
    try:
        author_uid = int(author_id)
    except (TypeError, ValueError):
        return False
    uids = await _subject_uids(
        db, row, subject=subject, target_user=target_user,
        speaker_author_id=speaker_author_id)
    return author_uid in uids


async def _fact_origin_class(db, row: dict, *, subject=None,
                             target_user=None,
                             speaker_author_id=None) -> str:
    """Класс по РЕАЛЬНЫМ сигналам строки факта и сохранённого сообщения.

    Классификатор ни разу не получает выдуманных `verification='verified'` /
    `method='direct_reference'`: у факта нет и не может быть «link-семантики» —
    только собственная атрибуция (F1) и сохранённое авторское сообщение.

    * `perspective='self'` — достаточный сигнал авторства (§2.2.1, ветвь 1);
    * `perspective IS NULL` + `self_report`/`direct_evidence` → `explicit_direct`
      только при совпадении uid автора сообщения с субъектом (§2.2.1, ветвь 2);
    * сохранённое сообщение-репост → `quote_forward` (§2.2.1(г)), не авторство;
    * иначе — `legacy_unknown` (нет второго сигнала, `confirmed` невозможен).
    """
    row = row or {}
    origin_class = graphrag_provenance.classify_origin_class(
        entity_type="graph_fact", source_row=row)
    if origin_class == ORIGIN_QUOTE_FORWARD:
        return origin_class
    msg = await _load_author_message(
        db, row.get("chat_id"), row.get("tg_message_id"))
    if _message_forwarded(msg) and origin_class in (
            ORIGIN_EXPLICIT_DIRECT, ORIGIN_LEGACY_UNKNOWN):
        return ORIGIN_QUOTE_FORWARD
    if origin_class == ORIGIN_EXPLICIT_DIRECT:
        return origin_class          # perspective='self' — достаточно
    if str(row.get("perspective") or "").strip():
        return origin_class          # явный сигнал есть — сверка не требуется
    if str(row.get("attribution_method") or "") \
            not in ("self_report", "direct_evidence"):
        return origin_class
    if str(row.get("forward_from") or "").strip():
        return origin_class          # репост/цитата — не авторство
    corroborated = await _authorship_corroborated(
        db, row, subject=subject, target_user=target_user,
        speaker_author_id=speaker_author_id)
    if corroborated:
        return ORIGIN_EXPLICIT_DIRECT
    return ORIGIN_LEGACY_UNKNOWN


def _evidence_plan(*, origin_class: str, row: dict, origin: str | None,
                   source_ref_id: int | None) -> dict:
    """План записи основания ребра, выведенный из класса (§2.2/§2.3).

    Атрибуция берётся из САМОГО ФАКТА, а не из сообщения: `perspective`,
    `attribution_method` и `forward_from` пишутся в `graph_facts`, поэтому
    пересказ/репост нельзя классифицировать как прямое утверждение автора.
    Обратного влияния «план → класс» нет.
    """
    row = row or {}
    if provenance.is_self_referential_origin(origin) \
            or provenance.is_self_referential_origin(row.get("origin")):
        return dict(_BOT_SELF_PLAN)

    if str(row.get("attribution_method") or "") == "world_knowledge":
        if source_ref_id is not None:
            return dict(_WORLD_KNOWLEDGE_PLAN)
        # Цепочка (сообщение автора) не разрешена → запись без подтверждения
        # и без класса-обещания: `unknown`/`unknown` на строке факта.
        return dict(_EVIDENCE_PLANS[ORIGIN_LEGACY_UNKNOWN])

    plan = dict(_EVIDENCE_PLANS.get(origin_class,
                                    _EVIDENCE_PLANS[ORIGIN_LEGACY_UNKNOWN]))
    if plan["root"] == "message" and source_ref_id is None:
        # Адреса сообщения нет — независимость не заявляем (§2.3/R-1).
        plan = dict(_NO_ADDRESS_PLAN)
    return plan


async def attach_fact_edge_evidence(
        db, *, chat_id: int, fact_id, source_ref_id: int | None = None,
        origin: str | None = None, edge_ids: list[int] | None = None,
        subject: str | None = None, target_user: str | None = None,
        speaker_author_id: int | None = None,
        established_at: int = 0,
        extractor_version: str | None = None) -> list[int]:
    """Основание ребра выводится из атрибуции факта (§2.2/§2.3, MEM-03.4).

    * прямое утверждение автора (perspective='self' ИЛИ подтверждённое
      сохранённым сообщением того же автора) → сообщение автора,
      `supports/verified/independent`;
    * пересказ третьего лица → `reported_third_party`, не независимый корень;
    * репост/цитата → `quote_forward`, не отдельное подтверждение;
    * производное/legacy → не подтверждение;
    * собственный вывод бота → строка факта бота, `self_referential` (R-3),
      сообщение человека источником реплики бота НЕ становится.

    `edge_ids` позволяет привязать основание к конкретному ребру (агрегат/
    повторная обработка); иначе берутся рёбра этого факта.
    """
    if not relation_evidence_enabled():
        return []
    targets = ([int(v) for v in edge_ids] if edge_ids
               else await edge_ids_for_fact(db, chat_id, fact_id))
    if not targets:
        return []          # нет ребра из этого факта — ни ref, ни link не создаём
    row = await _load_fact_row(db, chat_id, fact_id)
    origin_class = await _fact_origin_class(
        db, row, subject=subject, target_user=target_user,
        speaker_author_id=speaker_author_id)
    plan = _evidence_plan(
        origin_class=origin_class, row=row, origin=origin,
        source_ref_id=source_ref_id)

    if plan["root"] == "message" and source_ref_id is not None:
        root_ref_id: int | None = int(source_ref_id)
    else:
        root_ref_id = await provenance.resolve_source_ref(
            db, provenance.graph_fact_source_ref(chat_id, fact_id))
    if root_ref_id is None:
        return []

    attached: list[int] = []
    for edge_id in targets:
        edge_ref = await attach_edge_evidence(
            db, chat_id=chat_id, edge_id=edge_id, source_ref_id=root_ref_id,
            link_type=plan["link_type"], method=plan["method"],
            verification=plan["verification"],
            independence=plan["independence"], basis=plan["basis"],
            established_at=established_at,
            extractor_version=extractor_version)
        if edge_ref is not None:
            attached.append(int(edge_id))
    if attached:
        _emit_edge_evidence(chat_id, attached, plan["independence"])
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
        verification=str(link.get("verification") or "unknown"),
        basis=link.get("basis"))
    try:
        return OriginClass(value)
    except ValueError:                                    # pragma: no cover
        return OriginClass.LEGACY_UNKNOWN


def _assertion_mode(origin_class: OriginClass, entity_type: str | None,
                    row: dict):
    """Модальность основания (§3.3.1) с учётом подтверждённого авторства.

    `explicit_direct` означает «прямое утверждение подтверждённого автора»
    (§2.2.1), поэтому пара `explicit_direct` + `assertion_mode='unknown'`
    запрещена контрактом (§3.3.1). Авторство уже доказано вторым реальным
    сигналом на записи, поэтому модальность — `asserted`. Замороженный
    `memory_contracts.resolve_assertion_mode` не меняется: он описывает
    сигналы строки, а не подтверждённость авторства.
    """
    mode = _assertion_mode_for(entity_type, row)
    if origin_class is OriginClass.EXPLICIT_DIRECT \
            and mode is AssertionMode.UNKNOWN:
        return AssertionMode.ASSERTED
    return mode


def _source_view(link: dict, ref: dict, row: dict) -> RelationSourceView:
    entity_type = str(ref.get("entity_type") or "")
    settled_at = int(link.get("established_at") or 0) or int(time.time())
    origin_class = _origin_class(entity_type, row, link)
    return RelationSourceView(
        link_type=str(link.get("link_type") or ""),
        origin_class=origin_class,
        verification=str(link.get("verification") or "unknown"),
        independence=str(link.get("independence") or "unknown"),
        established_at=max(1, settled_at),
        method=str(link.get("method") or "unknown"),
        kind=_source_kind(ref),
        assertion_mode=_assertion_mode(origin_class, entity_type, row),
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
    # `legacy_unknown` — не «основание без подтверждения», а отсутствие
    # происхождения (R-7): статус `unverified`, не `tentative`.
    if any(s.link_type in SUPPORTING_LINK_TYPES
           and s.origin_class is not OriginClass.LEGACY_UNKNOWN
           for s in sources):
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
    legacy_only = (bool(sources) and independent == 0
                   and legacy_count == len(sources))
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
        "explanation": _explanation_for(status, sources,
                                        bare=bare_legacy or legacy_only),
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
