"""mca-06 (ADR-1028-9 D7/D8/D10, spec §5–§8.6) — блоки D+E глубокого сна.

Ядро независимости оснований, мост-валидатора, 10-статусной матрицы,
типизации исторических якорей (REUSE `services/provenance.py`), раскрытия
цепочки, версий (supersede), bounded-очереди пересмотра, анти-самоподтверждения
and области/времени применимости убеждения.

Kill-switches (env-only, default ON; OFF = бит-в-бит 2.58.48):
  * `MCA_DREAM_EVIDENCE_TYPING_ENABLED` — слои D (T-4713…T-4716) и E
    (T-4717/T-4718/T-4719/T-4721/T-4722);
  * `MCA_DREAM_REVISION_QUEUE_ENABLED` — очередь пересмотра (T-4720).

Второй provenance-контракт/таблица/словарь статусов НЕ создаётся: REUSE
`SourceRef`/`EvidenceLink`, типы `message`/`graph_fact`, `(chat_id,
tg_message_id)` mca-03.
"""
from __future__ import annotations

import dataclasses
import logging
import re
from dataclasses import dataclass, field

from services import mca_gates
from services import provenance

logger = logging.getLogger(__name__)

# ── 10-статусная матрица (spec §7.1, D6) — словарь ОДИН ─────────────────────

DREAM_STATUSES: tuple[str, ...] = (
    "disabled", "error", "no_context", "no_anchors", "insufficient_evidence",
    "unchanged", "duplicate", "budget", "cooldown", "written",
)

# Маппинг старых кодов dream_worker в канонические (D6): `ok`→`written`,
# `budget_skip`/`daily_limit`→`budget`, `no_memory`→`disabled`+detail.
LEGACY_STATUS_MAP: dict[str, str] = {
    "ok": "written",
    "budget_skip": "budget",
    "daily_limit": "budget",
    "no_memory": "disabled",
}

# Служебные внутренние reason-коды (отчёт/трассировка), НЕ статусы результата.
INTERNAL_REASON_CODES = frozenset({
    "no_memory", "cooldown_read", "packet_build", "rag_failed", "llm_error",
    "parse_error", "paradigm_write", "budget_skip", "daily_limit",
})


def map_status(legacy: str) -> str:
    """Старый/внутренний код → канонический статус (идемпотентно)."""
    key = str(legacy or "").strip()
    return LEGACY_STATUS_MAP.get(key, key)


def status_matrix() -> dict:
    """Канонический словарь статусов (для отчёта/теста единого источника)."""
    return {"statuses": list(DREAM_STATUSES),
            "legacy_map": dict(LEGACY_STATUS_MAP),
            "internal_reasons": sorted(INTERNAL_REASON_CODES)}


# ── T-4729/AM-3 (spec §8.6): отрицательная граница ядра характера ──────────
# DreamWorker (обе traits-ветки + ветка парадигм) пишет ТОЛЬКО в существующий
# derived-слой: `graph_facts` (origin='derived_belief') и `persona_traits`
# (`bot_persona.append_traits`/`record_trait_status`). Ядро характера владельца
# (mca-18: каноничный owner-configured persona-объект, его схема и кеш) здесь
# НЕ реализуется и НЕ эскизируется; write-путь к нему из sleep-контура НЕ
# существует (THR-8). Обновления интересов/отношений/состояния — derived-слой,
# как сегодня. Граница держится структурой кода (отсутствие write-пути), а не
# runtime-флагом.

# Write-API ядра характера (mca-18) — недоступны sleep-контуру.
CHARACTER_CORE_WRITE_API = frozenset({
    "save_persona", "set_persona", "update_persona_core",
    "set_character_core", "write_self_model", "update_owner_core",
})
# Разрешённый из сна derived-слой (не ядро).
SLEEP_DERIVED_WRITE_API = frozenset({
    "append_traits", "record_trait_status",
})


def character_core_boundary() -> dict:
    """Контракт границы AM-3 (для теста/аудита): список write-API ядра,
    недоступных из сна. `core_zone='mca-18'` — объект ядра вне mca-06."""
    return {"core_zone": "mca-18",
            "forbidden_core_api": sorted(CHARACTER_CORE_WRITE_API),
            "allowed_derived_api": sorted(SLEEP_DERIVED_WRITE_API)}


def character_core_write_blocked(api_name: str) -> bool:
    """True, если `api_name` — write-API ядра характера (попытка записи из сна
    → путь не существует/блокирован). False — derived-слой либо неизвестно."""
    return str(api_name or "") in CHARACTER_CORE_WRITE_API


# ── независимость оснований по первичным событиям (T-4713/T-4721) ───────────

def _item_text(item) -> str:
    if isinstance(item, dict):
        return str(item.get("fact") or item.get("summary")
                   or item.get("title") or "")
    if isinstance(item, (tuple, list)) and len(item) > 1:
        return str(item[1] or "")
    return str(item or "")


def primary_event_key(item) -> tuple:
    """Каноническая идентичность основания.

    Приоритет: `(chat_id, tg_message_id)` (mca-03) → `item_id` (эпизод) →
    `id` факта (SourceRef-идентичность) → нормализованный текст. Несколько
    пересказов одного сообщения → один ключ (§5.1, MCA05-R2 «тема ≠ событие»).
    """
    if isinstance(item, dict):
        tg = item.get("tg_message_id")
        if tg is not None:
            try:
                tg = int(tg)
            except (TypeError, ValueError):
                pass
            return ("tg", item.get("chat_id"), tg)
        item_id = item.get("item_id")
        if item_id:
            return ("item", str(item_id))
        fid = item.get("id")
        if fid is not None:
            return ("fact", fid)
    return ("text", _item_text(item).strip().casefold()[:200])


def is_resolved_anchor(item) -> bool:
    """Есть ли у якоря трассируемая идентичность (не honest unknown, §5.4).

    Текст без `(chat_id, tg_message_id)`/SourceRef-id — NOT confirmed."""
    return primary_event_key(item)[0] in ("tg", "item", "fact")


def is_bot_self(item) -> bool:
    """Основание канала `bot_self_reply`/собственный вывод бота (T-4721).

    REUSE `provenance.is_self_referential_origin` (mca-22): «вывод → пересказ →
    усиление» не является независимым подтверждением."""
    if not isinstance(item, dict):
        return False
    if item.get("self_referential"):
        return True
    for key in ("origin", "attribution_method", "source_kind", "source_channel"):
        val = item.get(key)
        if val and provenance.is_self_referential_origin(str(val)):
            return True
    return False


def independent_events(items) -> list[tuple]:
    """Уникальные независимые первичные события (bot_self исключён)."""
    seen: list[tuple] = []
    for item in list(items or []):
        if is_bot_self(item):
            continue
        key = primary_event_key(item)
        if key in seen:
            continue
        seen.append(key)
    return seen


def count_independent_events(items) -> int:
    return len(independent_events(items))


def excluded_bot_self(items) -> int:
    """Число оснований, исключённых из independence-подсчёта (bot_self)."""
    return sum(1 for it in (items or []) if is_bot_self(it))


def dedup_anchors(items) -> list:
    """Основания без дублей по первичному событию (недубльность §5.4)."""
    seen: set = set()
    out: list = []
    for item in list(items or []):
        key = primary_event_key(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


# ── мост-валидатор «раньше → сейчас» (T-4714/T-4716, §5.3) ──────────────────

_WORD_RE = re.compile(r"[a-zа-яё]{5,}", re.IGNORECASE)

# Маркеры дрейфа/противоречия: вывод не отвергается, а сужается/помечается
# спорным (EvidenceLink `contradicts`, §5.3 п.4).
CONTRADICTION_MARKERS = (
    "больше не", "уже не", "перестал", "перестала", "перестали", "бросил",
    "бросила", "однако", "вместо", "наоборот", "перестало",
)


def _tokens(text) -> list[str]:
    """Значимые токены (len≥5, casefold) — как `significant_tokens`."""
    return [m.group(0).casefold() for m in _WORD_RE.finditer(str(text or ""))]


def _anchor_ts(item) -> int | None:
    if isinstance(item, dict):
        ts = item.get("message_timestamp") or item.get("rag_ts") \
            or item.get("created_at")
    elif isinstance(item, (tuple, list)) and len(item) > 2:
        ts = item[2]
    else:
        ts = None
    try:
        ts = int(ts)
        return ts if ts > 0 else None
    except (TypeError, ValueError):
        return None


def _packet_texts(packet: dict) -> list[str]:
    out: list[str] = []
    for row in (packet.get("beliefs") or []) + (packet.get("recent") or []):
        if isinstance(row, dict) and str(row.get("fact") or "").strip():
            out.append(str(row.get("fact")))
    return out


def _packet_participants(packet: dict) -> set[str]:
    out: set[str] = set()
    for row in (packet.get("beliefs") or []) + (packet.get("recent") or []):
        if isinstance(row, dict) and row.get("target_user"):
            out.add(str(row.get("target_user")).casefold())
    return out


def _new_period_ts(packet: dict, now: int) -> int:
    """Время «сейчас»: max created_at свежих убеждений пакета, иначе now."""
    stamps = []
    for row in (packet.get("beliefs") or []):
        if isinstance(row, dict):
            try:
                ts = int(row.get("created_at") or 0)
            except (TypeError, ValueError):
                ts = 0
            if ts > 0:
                stamps.append(ts)
    return max(stamps) if stamps else int(now)


@dataclass
class BridgeValidation:
    """Результат 5 обязательных проверок моста (§5.3)."""
    ok: bool
    reason: str | None = None
    checks: dict = field(default_factory=dict)
    subject: str | None = None
    old_ts: int | None = None
    new_ts: int | None = None
    contradictions: list = field(default_factory=list)
    narrowed: bool = False
    applicability: dict = field(default_factory=dict)
    independent_events: int = 0


def _detect_contradictions(text: str, anchor_items) -> list[str]:
    """Опровергающие/дрейфовые основания: маркер дрейфа в тексте якоря при
    смысловой связке с выводом (не «произвольная пара старых фактов»)."""
    t_tokens = set(_tokens(text))
    found: list[str] = []
    for item in anchor_items or []:
        atext = _item_text(item).casefold()
        if not atext or not (t_tokens & set(_tokens(atext))):
            continue
        for marker in CONTRADICTION_MARKERS:
            if marker in atext:
                found.append(marker)
                break
    return found


def build_applicability(*, scope=None, valid_from=None, valid_to=None,
                        narrowed: bool = False) -> dict:
    """Поля применимости/времени убеждения (AM-5, §8.6) — JSON без DDL."""
    out = {
        "applicability_scope": scope,
        "valid_from": int(valid_from) if valid_from is not None else None,
        "valid_to": int(valid_to) if valid_to is not None else None,
    }
    if narrowed:
        out["narrowed"] = True
    return out


def validate_bridge(text: str, packet: dict, anchor_items, *, now: int,
                    subject: str | None = None,
                    independent_count: int | None = None) -> BridgeValidation:
    """5 обязательных проверок до `written` (§5.3, T-4714/T-4716).

    (1) субъект в обоих периодах; (2) «раньше» строго раньше «сейчас»;
    (3) смысловой мост; (4) противоречия/дрейф (вывод сужается, не
    отвергается); (5) источник резолвится до первичного сообщения.
    """
    anchors = list(anchor_items or [])
    t_tokens = set(_tokens(text))
    packet_texts = _packet_texts(packet)
    packet_tokens: set[str] = set()
    for ptxt in packet_texts:
        packet_tokens |= set(_tokens(ptxt))
    anchor_tokens: set[str] = set()
    for a in anchors:
        anchor_tokens |= set(_tokens(_item_text(a)))

    checks: dict[str, bool] = {}
    # (1) субъект: явный → участники пакета/якорей → пересечение токенов.
    subj = str(subject).casefold() if subject else None
    participants = _packet_participants(packet)
    subject_present = bool(
        (subj and (subj in participants or subj in anchor_tokens))
        or (participants & anchor_tokens)
        or (anchor_tokens & packet_tokens))
    checks["subject"] = subject_present

    # (2) временная последовательность: «раньше» строго раньше «сейчас».
    old_ts = max((_anchor_ts(a) or 0 for a in anchors), default=0) or None
    new_ts = _new_period_ts(packet, now)
    time_ok = bool(old_ts is not None and old_ts < int(new_ts))
    checks["time_order"] = time_ok

    # (3) смысловой мост: вывод связан со свежим контекстом.
    bridge_ok = bool(t_tokens & packet_tokens)
    checks["semantic_bridge"] = bridge_ok

    # (4) противоречия/дрейф — фиксируются, но не блокируют (сужение).
    contradictions = _detect_contradictions(text, anchors)
    checks["no_contradiction"] = not contradictions
    narrowed = bool(contradictions)

    # (5) источник резолвится до первичного сообщения (honest unknown запрещён).
    resolved = all(is_resolved_anchor(a) for a in anchors) and bool(anchors)
    checks["source_resolved"] = resolved

    reason = None
    if not resolved:
        reason = "unresolved_source"
    elif not time_ok:
        reason = "time_order"
    elif not subject_present:
        reason = "no_subject"
    elif not bridge_ok:
        reason = "no_bridge"

    applicability = build_applicability(
        scope=(subject or (sorted(anchor_tokens)[0] if anchor_tokens else None))
        if narrowed else None,
        valid_from=old_ts if narrowed else None,
        valid_to=new_ts if narrowed else None,
        narrowed=narrowed)
    return BridgeValidation(
        ok=(reason is None), reason=reason, checks=checks, subject=subject,
        old_ts=old_ts, new_ts=new_ts, contradictions=contradictions,
        narrowed=narrowed, applicability=applicability,
        independent_events=int(independent_count or 0))


# ── валидатор ссылок (T-4717, §5.4) — существование/недубльность ────────────

@dataclass
class LinkValidation:
    ok: bool
    unresolved: list = field(default_factory=list)
    duplicates: list = field(default_factory=list)
    resolved: int = 0


def validate_links(anchor_items, *, existing_pairs=None) -> LinkValidation:
    """Существование + недубльность ссылок (без создания записей).

    `existing_pairs` — множество `(entity_type, entity_id)` уже
    зарегистрированных SourceRef (read-only). Отсутствие → honest unknown."""
    existing = set(existing_pairs or ())
    known = existing_pairs is not None
    seen: set = set()
    unresolved: list = []
    duplicates: list = []
    resolved = 0
    for item in list(anchor_items or []):
        key = primary_event_key(item)
        if key in seen:
            duplicates.append(key)
            continue
        seen.add(key)
        ref = anchor_source_ref(item.get("chat_id") if isinstance(item, dict)
                                else None, item)
        pair = (ref.entity_type, str(ref.entity_id)) if ref is not None else None
        if pair is None or (known and pair not in existing):
            unresolved.append(key)
            continue
        resolved += 1
    return LinkValidation(ok=(not unresolved and not duplicates),
                          unresolved=unresolved, duplicates=duplicates,
                          resolved=resolved)


# ── типизация исторических якорей (T-4717, §8.1) ────────────────────────────

def anchor_source_ref(chat_id, item):
    """SourceRef исторического якоря: message (mca-03) приоритетно, иначе
    graph_fact. REUSE `provenance.message_source_ref`/`graph_fact_source_ref`."""
    if not isinstance(item, dict):
        return None
    tg = item.get("tg_message_id")
    if tg is not None:
        try:
            tg = int(tg)
        except (TypeError, ValueError):
            return None
        entity_id = str(item.get("message_entity_id") or f"tg:{tg}")
        return provenance.message_source_ref(
            chat_id=chat_id, entity_id=entity_id, tg_message_id=tg)
    fid = item.get("id")
    if fid is not None:
        return provenance.graph_fact_source_ref(chat_id, fid)
    return None


def independence_label(item) -> str:
    return "self_referential" if is_bot_self(item) else "independent"


async def record_anchor_items_provenance(db, *, fact_id: int, chat_id,
                                         anchor_items) -> dict:
    """Типизировать исторические `anchor_items` тем же контрактом, что и
    входные `source_ids` (T-4717, A14): `derived_from` EvidenceLink на
    paradigm. Второй контракт/таблица запрещены. Fail-open (возврат счётчика).
    """
    if not mca_gates.dream_evidence_typing_enabled():
        return {"recorded": 0, "unknown": 0}
    try:
        obj = await provenance.resolve_source_ref(
            db, provenance.graph_fact_source_ref(chat_id, fact_id))
    except Exception:
        logger.warning("[dream_evidence] anchor provenance object failed | "
                       "id=%s", fact_id, exc_info=True)
        return {"recorded": 0, "unknown": 0}
    if obj is None:
        return {"recorded": 0, "unknown": 0}
    recorded = 0
    unknown = 0
    seen: set = set()
    for item in list(anchor_items or []):
        key = primary_event_key(item)
        if key in seen:
            continue
        seen.add(key)
        ref = anchor_source_ref(chat_id, item)
        if ref is None:
            unknown += 1
            continue
        try:
            src_id = await provenance.resolve_source_ref(db, ref)
        except Exception:
            unknown += 1
            continue
        if src_id is None:
            unknown += 1
            continue
        method = ("reply_context" if ref.entity_type == "message"
                  else "direct_reference")
        try:
            await provenance.add_evidence_link(db, provenance.EvidenceLink(
                subject_ref_id=obj, source_ref_id=src_id,
                link_type="derived_from", method=method,
                verification="verified", independence=independence_label(item),
                basis="dream historical anchor"))
        except Exception:
            logger.warning("[dream_evidence] anchor link failed — fail-open",
                           exc_info=True)
            unknown += 1
            continue
        recorded += 1
    return {"recorded": recorded, "unknown": unknown}


# ── версии / supersede (T-4719, §8.3) ───────────────────────────────────────

async def link_supersedes(db, *, chat_id, new_fact_id: int, old_fact_id: int,
                          claim_key: str | None = None) -> bool:
    """`supersedes` EvidenceLink новой версии парадигмы к предыдущей (mca-22).

    Старая версия остаётся читаемой (запись не затирается). Fail-open."""
    if not mca_gates.dream_evidence_typing_enabled():
        return False
    if not new_fact_id or not old_fact_id or int(new_fact_id) == int(old_fact_id):
        return False
    try:
        new_ref = await provenance.resolve_source_ref(
            db, provenance.graph_fact_source_ref(chat_id, new_fact_id))
        old_ref = await provenance.resolve_source_ref(
            db, provenance.graph_fact_source_ref(chat_id, old_fact_id))
        if new_ref is None or old_ref is None:
            return False
        await provenance.add_evidence_link(db, provenance.EvidenceLink(
            subject_ref_id=new_ref, source_ref_id=old_ref,
            link_type="supersedes", method="direct_reference",
            verification="verified", independence="independent",
            claim_key=claim_key, basis="paradigm new version"))
        return True
    except Exception:
        logger.warning("[dream_evidence] supersedes link failed — fail-open | "
                       "new=%s old=%s", new_fact_id, old_fact_id, exc_info=True)
        return False


async def link_contradicts(db, *, chat_id, fact_id: int, anchor_item) -> bool:
    """EvidenceLink `contradicts` для опровергающего/дрейфового основания."""
    if not mca_gates.dream_evidence_typing_enabled():
        return False
    try:
        obj = await provenance.resolve_source_ref(
            db, provenance.graph_fact_source_ref(chat_id, fact_id))
        src = anchor_source_ref(chat_id, anchor_item)
        if obj is None or src is None:
            return False
        src_id = await provenance.resolve_source_ref(db, src)
        if src_id is None:
            return False
        await provenance.add_evidence_link(db, provenance.EvidenceLink(
            subject_ref_id=obj, source_ref_id=src_id,
            link_type="contradicts", method="direct_reference",
            verification="verified", independence=independence_label(anchor_item),
            basis="dream bridge contradiction"))
        return True
    except Exception:
        logger.warning("[dream_evidence] contradicts link failed — fail-open",
                       exc_info=True)
        return False


def topic_overlap(text_a: str, text_b: str) -> int:
    return len(set(_tokens(text_a)) & set(_tokens(text_b)))


def find_supersede_candidate(rows, text: str, *, min_overlap: int = 2):
    """Предыдущая парадигма, которую вытесняет новая версия (§8.3).

    `rows` — строки graph_facts (belief_meta внутри). Кандидат — самая свежая
    (max id) парадигма с достаточным тематическим пересечением и иным
    dedup_key/источником."""
    best = None
    for row in rows or []:
        meta = _belief_meta(row)
        if meta.get("type") != "paradigm":
            continue
        rid = row.get("id")
        if rid is None:
            continue
        if topic_overlap(text, str(row.get("fact") or "")) < int(min_overlap):
            continue
        if best is None or int(rid) > int(best.get("id")):
            best = row
    return int(best["id"]) if best is not None else None


def _belief_meta(row) -> dict:
    import json
    raw = row.get("belief_meta") if isinstance(row, dict) else None
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        val = json.loads(str(raw))
        return val if isinstance(val, dict) else {}
    except (ValueError, TypeError):
        return {}


# ── область/время убеждения в belief_meta (T-4722, AM-5/§8.6) ───────────────

def merge_applicability(meta: dict | None, *, applicability: dict | None = None
                        ) -> dict:
    """Аддитивно дополнить belief_meta полями AM-5 (JSON, без DDL)."""
    out = dict(meta or {})
    for key in ("applicability_scope", "valid_from", "valid_to", "narrowed"):
        if applicability and key in applicability:
            out[key] = applicability[key]
    return out


# ── bounded очередь пересмотра зависимых выводов (T-4720, §8.4) ─────────────

@dataclass
class RevisionQueue:
    """Ограниченная очередь пересмотра: cap за цикл, приоритет ниже прямых.

    Каскад не мгновенный и не бесконечный: `enqueue` усекается по cap,
    `drain` отдаёт не более `limit` за раз. paused/resume — kill-switch слой.
    """
    cap: int = 20
    paused: bool = False
    _items: list = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self._items)

    def enqueue(self, keys, *, priority: int = 0) -> int:
        """Поставить зависимые выводы в очередь; вернуть число принятых.

        Дедуп по ключу; при переполнении cap — приоритетные удерживаются,
        низкоприоритетные отклоняются (bounded, не теряет споры)."""
        if self.paused:
            return 0
        cap = max(1, int(self.cap))
        added = 0
        known = {k for _, _, k in self._items}
        for key in keys or []:
            k = _hashable(key)
            if k in known:
                continue
            if len(self._items) >= cap:
                break
            self._items.append((-int(priority), int(len(self._items)), k))
            known.add(k)
            added += 1
        self._items.sort()
        return added

    def drain(self, limit: int | None = None) -> list:
        """Забрать не более `limit` (по умолчанию cap) элементов."""
        take = max(0, int(limit if limit is not None else self.cap))
        out = [k for _, _, k in self._items[:take]]
        self._items = self._items[take:]
        return out

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def clear(self) -> None:
        self._items = []


def _hashable(key):
    if isinstance(key, (list, set)):
        return tuple(key)
    return key


_REVISION_QUEUE: RevisionQueue | None = None


def get_revision_queue(*, cap: int | None = None) -> RevisionQueue:
    global _REVISION_QUEUE
    if _REVISION_QUEUE is None:
        _REVISION_QUEUE = RevisionQueue(
            cap=int(cap or mca_gates.dream_revision_queue_cap()))
    return _REVISION_QUEUE


def reset_revision_queue() -> None:
    global _REVISION_QUEUE
    _REVISION_QUEUE = None


def enqueue_dependent_revisions(keys, *, cap: int | None = None,
                                priority: int = 0) -> int:
    """Вход в очередь пересмотра. Kill-switch OFF → 0 (прежнее поведение)."""
    if not mca_gates.dream_revision_queue_enabled():
        return 0
    q = get_revision_queue(cap=cap)
    q.cap = int(cap or q.cap)
    return q.enqueue(keys, priority=priority)


# ── раскрытие цепочки (T-4718, §8.2) ────────────────────────────────────────

async def _fact_row(db, fact_id: int) -> dict | None:
    try:
        cursor = await db.db.execute(
            "SELECT id, chat_id, fact, status, supersedes FROM graph_facts "
            "WHERE id = ?", (int(fact_id),))
        row = await cursor.fetchone()
        return dict(row) if row is not None else None
    except Exception:
        return None


async def _expand_ref(db, ref_id: int, *, chat_id, depth: int,
                      max_nodes: int, seen_refs: set, messages: list,
                      anchors: list) -> None:
    if len(anchors) >= max_nodes or ref_id in seen_refs:
        return
    seen_refs.add(ref_id)
    src = await provenance.get_source_ref(db, ref_id)
    if src is None:
        return
    node = {
        "source_ref_id": int(ref_id),
        "store": src.get("store"),
        "entity_type": src.get("entity_type"),
        "entity_id": src.get("entity_id"),
        "chat_id": src.get("chat_id"),
        "tg_message_id": src.get("tg_message_id"),
        "resolution": src.get("resolution"),
    }
    anchors.append(node)
    if node["entity_type"] == "message":
        messages.append({
            "chat_id": node["chat_id"],
            "tg_message_id": node["tg_message_id"],
            "entity_id": node["entity_id"],
        })
    elif node["entity_type"] == "graph_fact" and depth < 2:
        # fact-якорь раскрывается до его исходного сообщения (1 прыжок).
        try:
            mapping = await db.resolve_source_ref_ids(
                chat_id, [("graph_fact", str(node["entity_id"]))])
        except Exception:
            mapping = {}
        sub = mapping.get(("graph_fact", str(node["entity_id"])))
        if sub:
            links = await provenance.get_evidence_links(db, sub)
            for link in links:
                await _expand_ref(db, link.get("source_ref_id"),
                                  chat_id=chat_id, depth=depth + 1,
                                  max_nodes=max_nodes, seen_refs=seen_refs,
                                  messages=messages, anchors=anchors)
                if len(anchors) >= max_nodes:
                    break


async def expand_chain(db, *, chat_id, fact_id: int,
                       max_nodes: int = 50) -> dict:
    """Цепочка парадигма → основания/якоря → факты → сообщения (A14).

    Read-only: SourceRef/EvidenceLink v17-таблицы REUSE (второй контракт
    запрещён). Резолв до пары `(chat_id, tg_message_id)` mca-03; отсутствие
    ссылки → честная пустота (не подтверждение)."""
    out = {
        "chat_id": chat_id,
        "fact_id": int(fact_id),
        "anchors": [],
        "messages": [],
        "delta": None,
        "truncated": False,
    }
    row = await _fact_row(db, fact_id)
    if row is not None:
        old_id = row.get("supersedes")
        delta = {"new": str(row.get("fact") or "")}
        if old_id:
            old = await _fact_row(db, int(old_id))
            delta["old"] = str(old.get("fact") or "") if old else None
            delta["supersedes_fact_id"] = int(old_id)
        out["delta"] = delta
    try:
        mapping = await db.resolve_source_ref_ids(
            chat_id, [("graph_fact", str(fact_id))])
    except Exception:
        mapping = {}
    subject = mapping.get(("graph_fact", str(fact_id)))
    if subject:
        links = await provenance.get_evidence_links(db, subject)
        for link in links:
            await _expand_ref(db, link.get("source_ref_id"), chat_id=chat_id,
                              depth=1, max_nodes=max_nodes, seen_refs=set(),
                              messages=out["messages"], anchors=out["anchors"])
            if len(out["anchors"]) >= max_nodes:
                out["truncated"] = True
                break
    return out
