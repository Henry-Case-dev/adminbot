"""Раунд 10.27 (MCA Wave 1, `mca-04a-provenance-contract`, ADR-1027-6).

Единый контракт происхождения памяти:

* **SourceRef** — типизированный opaque-адрес источника (`store` /
  `entity_type` / `entity_id` / `chat_id` / `revision`; для оригинала-сообщения
  дополнительно `tg_message_id` / `dataset_id` / `source_record_id`;
  `resolution` = resolved|unresolved|unknown). SQLite fact ID, PG row ID и
  Telegram message ID **не** взаимозаменяемы и не сравниваются между собой.
* **EvidenceLink** — связь «объект ↔ источник» с версиями, типом
  (`derived_from` / `supports` / `contradicts` / `mentions` / `supersedes`),
  способом (`method`), статусом проверки (`verification`), независимостью
  (`independence`), ключом утверждения (`claim_key`), версией экстрактора и
  кратким проверяемым основанием (`basis`), кодами проверок (`checks_json`).
* **Статусы** — `origin_status` (только происхождение) и **отдельные** поля
  `conflict_status` / `freshness_status` / `coverage_status` (+covered/total).

REUSE: `message_source_records`/`message_revisions`/`(chat_id, tg_message_id)`
(MCA-03), `source_ids`/`graph_facts` (Epic 1–3), `write_transaction`/`serialized`
(MCA-01), `emit_mca_event`/`mca_events` (MCA-13), `thread_chain` (F6),
MigrationStep (mca-14). Второй контракт идентичности/provenance запрещён.

R17: `basis` — короткое проверяемое основание без скрытого CoT; `checks_json` —
коды/enum; в события — только id/коды/`error_type`; сырой контекст не пишется.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from services import mca_gates

logger = logging.getLogger(__name__)

# Версия экстрактора/контракта — пишется в ссылки и статусы (наблюдаемость).
EXTRACTOR_VERSION = "mca-04a/v1"

# ── Допустимые значения (закрытые наборы, spec §4) ──────────────────────────
STORES = frozenset({"sqlite", "postgres", "telegram", "external", "legacy"})
ENTITY_TYPES = frozenset({
    "message", "graph_fact", "belief", "paradigm", "episode", "story",
    "dossier", "user", "media_asset", "unknown",
})
LINK_TYPES = frozenset({
    "derived_from", "supports", "contradicts", "mentions", "supersedes",
})
METHODS = frozenset({
    "direct_reference", "metadata", "exact_search", "semantic_search",
    "reply_context", "thread_context", "migration_backfill", "manual",
    "unknown",
})
VERIFICATIONS = frozenset({"verified", "rejected", "tentative", "unknown"})
INDEPENDENCES = frozenset({"independent", "self_referential", "unknown"})
ORIGIN_STATUSES = frozenset({
    "original", "reconstructed_support", "tentative", "unknown",
})
CONFLICT_STATUSES = frozenset({"none", "conflicting", "resolved", "unknown"})
FRESHNESS_STATUSES = frozenset({"current", "superseded", "stale", "unknown"})
COVERAGE_STATUSES = frozenset({"full", "partial", "none", "unknown"})
RESOLUTIONS = frozenset({"resolved", "unresolved", "unknown"})
ASSERTION_KINDS = frozenset({
    "biographical", "preference", "event", "relation", "opinion",
    "world_knowledge", "unknown",
})
ATTRIBUTION_METHODS = frozenset({
    "self_report", "third_party", "direct_evidence", "bot_self_reply",
    "world_knowledge", "unknown",
})
PROVENANCE_CHANNELS = frozenset({
    "live", "dossier_layer_a", "dossier_layer_b", "dream", "import", "unknown",
})

# Коды проверок восстановления (§8.2): author/object/time/negation/quote/joke/
# retelling/actuality. Значения — только коды, без текста (R17).
CHECK_KEYS: tuple[str, ...] = (
    "author", "object", "time", "negation", "quote", "joke", "retelling",
    "actuality",
)
CHECK_VALUES = frozenset({"ok", "failed", "unknown"})

# origin'ы собственных ответов бота → self_referential (не подтверждение).
BOT_ORIGINS = frozenset({"bot_self_reply", "bot_direct_reply"})

_PREFERENCE_MARKERS = (
    "любит", "нравится", "предпочитает", "обожает", "не любит", "терпеть",
    "ненавидит", "увлекается", "интересуется", "мечтает", "боится",
)


def provenance_enabled() -> bool:
    """Резолв `MCA_PROVENANCE_ENABLED` per-call (никогда не бросает)."""
    try:
        return mca_gates.provenance_enabled()
    except Exception:                                     # pragma: no cover
        return True


def attribution_enabled() -> bool:
    """Резолв `MCA_FACT_ATTRIBUTION_ENABLED` (инертен при provenance=OFF)."""
    try:
        return mca_gates.fact_attribution_enabled()
    except Exception:                                     # pragma: no cover
        return True


def reconstruction_enabled() -> bool:
    """Резолв `MCA_EVIDENCE_RECONSTRUCTION_ENABLED` (инертен при provenance=OFF)."""
    try:
        return mca_gates.evidence_reconstruction_enabled()
    except Exception:                                     # pragma: no cover
        return True


def _now(now: int | None) -> int:
    return int(time.time()) if now is None else int(now)


# ── SourceRef ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SourceRef:
    """Типизированный адрес источника (spec §4.1)."""

    store: str
    entity_type: str
    entity_id: str
    chat_id: int | None = None
    revision: str | None = None
    tg_message_id: int | None = None
    dataset_id: str | None = None
    source_record_id: str | None = None
    resolution: str = "unknown"

    def validate(self) -> "SourceRef":
        if self.store not in STORES:
            raise ValueError(f"SourceRef.store invalid: {self.store!r}")
        if self.entity_type not in ENTITY_TYPES:
            raise ValueError(
                f"SourceRef.entity_type invalid: {self.entity_type!r}")
        if not str(self.entity_id):
            raise ValueError("SourceRef.entity_id is empty")
        if self.resolution not in RESOLUTIONS:
            raise ValueError(
                f"SourceRef.resolution invalid: {self.resolution!r}")
        # `tg_message_id` только для сущности-сообщения (spec §4.1).
        if self.tg_message_id is not None and self.entity_type != "message":
            raise ValueError(
                "SourceRef.tg_message_id allowed only for entity_type='message'")
        return self

    @property
    def dedup_key(self) -> tuple:
        return (self.store, self.entity_type, str(self.entity_id),
                self.chat_id if self.chat_id is not None else -1,
                self.revision or "")

    def as_dict(self) -> dict:
        return {
            "store": self.store, "entity_type": self.entity_type,
            "entity_id": str(self.entity_id), "chat_id": self.chat_id,
            "revision": self.revision, "tg_message_id": self.tg_message_id,
            "dataset_id": self.dataset_id,
            "source_record_id": self.source_record_id,
            "resolution": self.resolution,
        }


def user_source_ref(chat_id: int, user_id, *,
                    resolution: str = "resolved") -> SourceRef:
    """SourceRef субъекта-пользователя (устойчивый ID — spec §4.5).

    Импорт без Telegram ID → `resolution='unresolved'` со стабильным
    `entity_id` (не выдуманный Telegram ID)."""
    return SourceRef(
        store="telegram", entity_type="user", entity_id=str(user_id),
        chat_id=chat_id if chat_id is not None else None,
        resolution=resolution)


def graph_fact_source_ref(chat_id: int, fact_id, *,
                          resolution: str = "resolved") -> SourceRef:
    return SourceRef(
        store="sqlite", entity_type="graph_fact", entity_id=str(fact_id),
        chat_id=chat_id if chat_id is not None else None,
        resolution=resolution)


def message_source_ref(*, chat_id, entity_id: str, tg_message_id=None,
                       dataset_id=None, source_record_id=None,
                       revision=None, resolution: str = "resolved") -> SourceRef:
    return SourceRef(
        store="sqlite", entity_type="message", entity_id=str(entity_id),
        chat_id=chat_id if chat_id is not None else None, revision=revision,
        tg_message_id=tg_message_id, dataset_id=dataset_id,
        source_record_id=source_record_id, resolution=resolution)


# ── EvidenceLink ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EvidenceLink:
    """Связь «объект ↔ источник» (spec §4.2)."""

    subject_ref_id: int
    source_ref_id: int
    link_type: str
    method: str
    verification: str = "unknown"
    independence: str = "unknown"
    claim_key: str | None = None
    extractor_version: str | None = EXTRACTOR_VERSION
    basis: str | None = None
    checks: dict | None = None
    established_at: int = 0

    def validate(self) -> "EvidenceLink":
        if self.link_type not in LINK_TYPES:
            raise ValueError(f"EvidenceLink.link_type invalid: {self.link_type!r}")
        if self.method not in METHODS:
            raise ValueError(f"EvidenceLink.method invalid: {self.method!r}")
        if self.verification not in VERIFICATIONS:
            raise ValueError(
                f"EvidenceLink.verification invalid: {self.verification!r}")
        if self.independence not in INDEPENDENCES:
            raise ValueError(
                f"EvidenceLink.independence invalid: {self.independence!r}")
        return self


def normalize_checks(checks: dict | None) -> str | None:
    """Проверки → JSON с кодами (R17-safe). Неизвестные значения → `unknown`."""
    if not checks:
        return None
    out: dict[str, str] = {}
    for key in CHECK_KEYS:
        if key in checks:
            val = str(checks.get(key) or "unknown").strip().lower()
            out[key] = val if val in CHECK_VALUES else "unknown"
    if not out:
        return None
    return json.dumps(out, ensure_ascii=True, sort_keys=True)


def safe_basis(text, limit: int = 160) -> str | None:
    """Краткое проверяемое основание без сырого контекста/CoT (R17)."""
    if text is None:
        return None
    cleaned = " ".join(str(text).split())
    if not cleaned:
        return None
    return cleaned[:limit]


def make_checks(**kwargs) -> dict:
    """Собрать словарь проверок из kwargs (только известные ключи)."""
    return {k: v for k, v in kwargs.items() if k in CHECK_KEYS}


# ── Семантика независимости и self-referential (A10) ────────────────────────

def is_self_referential_origin(origin: str | None) -> bool:
    """Собственные ответы бота не подтверждают факты о людях (spec §4.2)."""
    return str(origin or "").strip() in BOT_ORIGINS


def evidence_independent_count(links: list[dict]) -> int:
    """Число независимых подтверждающих доказательств (A10).

    Учитываются только `derived_from`/`supports`, `verification='verified'` и
    `independence='independent'`, уникальные по `source_ref_id`. Два вывода из
    одного события → один SourceRef → одно доказательство."""
    seen: set = set()
    for link in links or []:
        if str(link.get("link_type")) not in ("derived_from", "supports"):
            continue
        if str(link.get("verification")) != "verified":
            continue
        if str(link.get("independence")) != "independent":
            continue
        seen.add(link.get("source_ref_id"))
    return len(seen)


# ── БД-операции (REUSE `_provenance_*`; рантайм — через write_transaction) ──

async def resolve_source_ref(db, ref: SourceRef) -> int | None:
    """Get-or-create SourceRef (дедуп по store/type/id/chat/revision)."""
    ref.validate()
    if not provenance_enabled():
        return None

    async def _body(_conn):
        return await db._provenance_resolve_ref(
            store=ref.store, entity_type=ref.entity_type,
            entity_id=str(ref.entity_id), chat_id=ref.chat_id,
            revision=ref.revision, tg_message_id=ref.tg_message_id,
            dataset_id=ref.dataset_id, source_record_id=ref.source_record_id,
            resolution=ref.resolution, now=_now(None))

    return await db.write_transaction(_body, op_name="provenance_resolve_ref")


async def add_evidence_link(db, link: EvidenceLink) -> None:
    """Идемпотентная EvidenceLink (дедуп по объект+источник+тип+claim)."""
    link.validate()
    if not provenance_enabled():
        return

    async def _body(_conn):
        await db._provenance_link(
            link.subject_ref_id, link.source_ref_id, link.link_type,
            link.method, link.verification, link.independence,
            _now(link.established_at or None), claim_key=link.claim_key,
            basis=safe_basis(link.basis),
            checks_json=normalize_checks(link.checks),
            extractor_version=link.extractor_version)

    await db.write_transaction(_body, op_name="provenance_add_link")


async def set_provenance_status(
        db, object_ref_id: int, *, origin_status: str = "unknown",
        conflict_status: str | None = None, freshness_status: str | None = None,
        coverage_status: str | None = None, coverage_covered=None,
        coverage_total=None, extractor_version: str | None = EXTRACTOR_VERSION,
        now=None) -> None:
    """Записать статус 1:1 с объектным SourceRef (spec §4.3/D5).

    `conflict_status`/`freshness_status`/`coverage_status` (+covered/total)
    по умолчанию `None` = **сохранить ранее записанное** (на новой строке —
    `unknown`). Повторная запись `origin_status` (например, producer'ом) не
    затирает конфликт/актуальность/покрытие — это разные наблюдаемые поля
    (D5, D-MCA04A-4). Явная передача значения перезаписывает его."""
    if origin_status not in ORIGIN_STATUSES:
        raise ValueError(f"origin_status invalid: {origin_status!r}")
    if conflict_status is not None and conflict_status not in CONFLICT_STATUSES:
        raise ValueError(f"conflict_status invalid: {conflict_status!r}")
    if freshness_status is not None \
            and freshness_status not in FRESHNESS_STATUSES:
        raise ValueError(f"freshness_status invalid: {freshness_status!r}")
    if coverage_status is not None and coverage_status not in COVERAGE_STATUSES:
        raise ValueError(f"coverage_status invalid: {coverage_status!r}")
    if not provenance_enabled():
        return

    ts = _now(now)

    async def _body(_conn):
        cursor = await db.db.execute(
            "SELECT conflict_status, freshness_status, coverage_status, "
            "coverage_covered, coverage_total, extractor_version "
            "FROM mca_provenance_status WHERE object_ref_id = ?",
            (int(object_ref_id),))
        existing = await cursor.fetchone()

        def _keep(new, col, default="unknown"):
            if new is not None:
                return new
            if existing is not None and existing[col] is not None:
                return existing[col]
            return default

        await db.db.execute(
            "INSERT OR REPLACE INTO mca_provenance_status (object_ref_id, "
            "origin_status, conflict_status, freshness_status, coverage_status, "
            "coverage_covered, coverage_total, extractor_version, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (int(object_ref_id), origin_status,
             _keep(conflict_status, "conflict_status"),
             _keep(freshness_status, "freshness_status"),
             _keep(coverage_status, "coverage_status"),
             _keep(coverage_covered, "coverage_covered", None),
             _keep(coverage_total, "coverage_total", None),
             _keep(extractor_version, "extractor_version", None),
             ts))

    await db.write_transaction(_body, op_name="provenance_set_status")


async def get_provenance_status(db, object_ref_id: int) -> dict | None:
    cursor = await db.db.execute(
        "SELECT object_ref_id, origin_status, conflict_status, freshness_status, "
        "coverage_status, coverage_covered, coverage_total, extractor_version, "
        "updated_at FROM mca_provenance_status WHERE object_ref_id = ?",
        (int(object_ref_id),))
    row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def get_evidence_links(db, subject_ref_id: int) -> list[dict]:
    cursor = await db.db.execute(
        "SELECT link_id, subject_ref_id, source_ref_id, link_type, method, "
        "verification, independence, claim_key, extractor_version, basis, "
        "checks_json, established_at, created_at FROM mca_evidence_links "
        "WHERE subject_ref_id = ? ORDER BY link_id ASC",
        (int(subject_ref_id),))
    return [dict(r) for r in await cursor.fetchall()]


async def links_derived_from_source(db, source_ref_id: int) -> list[dict]:
    cursor = await db.db.execute(
        "SELECT link_id, subject_ref_id, source_ref_id, link_type "
        "FROM mca_evidence_links WHERE source_ref_id = ? ORDER BY link_id ASC",
        (int(source_ref_id),))
    return [dict(r) for r in await cursor.fetchall()]


# ── Запись происхождения факта (producer, FIX п.1/п.3) ──────────────────────

async def record_fact_provenance(
        db, *, fact_id: int, chat_id, origin: str | None,
        target_user: str | None = None, subject: str | None = None,
        object_: str | None = None, tg_message_id: int | None = None,
        assertion_kind: str | None = None,
        attribution_method: str | None = None,
        speaker_author_id: int | None = None,
        provenance_channel: str = "live",
        extractor_version: str | None = EXTRACTOR_VERSION,
        save_message_link: bool = True,
        now: int | None = None) -> dict:
    """Создать объектный/источниковый SourceRef, EvidenceLink и статус факта.

    * объект — `graph_fact` (store=sqlite, entity_type=graph_fact, id факта);
    * прямой источник — message SourceRef, **только** при сохранённом
      `tg_message_id` (иначе честный `unknown`, без выдуманного ID);
    * `origin_status='original'` — **только** при сохранённом прямом источнике;
      иначе `unknown`;
    * `independence='self_referential'` для origin'ов ответов бота.

    Возврат: `{"object_ref_id", "source_ref_id", "origin_status"}`.
    При `MCA_PROVENANCE_ENABLED=OFF` — no-op (паритет baseline)."""
    ts = _now(now)
    result = {"object_ref_id": None, "source_ref_id": None,
              "origin_status": "unknown"}
    if not provenance_enabled():
        return result
    obj_ref = await resolve_source_ref(
        db, graph_fact_source_ref(chat_id, fact_id))
    if obj_ref is None:
        return result
    result["object_ref_id"] = obj_ref

    origin_status = "unknown"
    source_ref_id = None
    self_ref = is_self_referential_origin(origin)
    if save_message_link and tg_message_id is not None and chat_id is not None:
        entity_id = await _message_entity_id(db, chat_id, tg_message_id)
        msg_ref = await resolve_source_ref(
            db, message_source_ref(chat_id=chat_id, entity_id=entity_id,
                                   tg_message_id=int(tg_message_id)))
        if msg_ref is not None:
            source_ref_id = msg_ref
            result["source_ref_id"] = msg_ref
            # Прямой источник сохранён при создании → original (spec §4.3).
            origin_status = "original"
            # Self-referential ответы бота не подтверждают (spec §4.2).
            await add_evidence_link(db, EvidenceLink(
                subject_ref_id=obj_ref, source_ref_id=msg_ref,
                link_type="derived_from",
                method="direct_reference",
                verification="verified",
                independence=("self_referential" if self_ref else "independent"),
                extractor_version=extractor_version,
                basis="saved direct tg_message_id",
                established_at=ts))

    # Аддитивные колонки факта: субъект/атрибуция/тип/автор/канал.
    await update_fact_provenance_columns(
        db, fact_id=fact_id, assertion_kind=assertion_kind,
        attribution_method=attribution_method,
        speaker_author_id=speaker_author_id,
        extractor_version=extractor_version,
        provenance_channel=provenance_channel)

    await set_provenance_status(
        db, obj_ref, origin_status=origin_status,
        extractor_version=extractor_version, now=ts)
    result["origin_status"] = origin_status
    return result


async def update_fact_provenance_columns(
        db, *, fact_id: int, assertion_kind=None, attribution_method=None,
        speaker_author_id=None, extractor_version=None,
        provenance_channel=None, subject_ref_id=None) -> None:
    """Аддитивно заполнить provenance-колонки `graph_facts` (None — не менять)."""
    if not provenance_enabled():
        return
    sets: list[str] = []
    params: list = []
    for col, val in (
            ("subject_ref_id", subject_ref_id),
            ("attribution_method", attribution_method),
            ("assertion_kind", assertion_kind),
            ("speaker_author_id", speaker_author_id),
            ("extractor_version", extractor_version),
            ("provenance_channel", provenance_channel)):
        if val is None:
            continue
        sets.append(f"{col} = ?")
        params.append(val)

    async def _body(_conn):
        if not sets:
            return
        params.append(int(fact_id))
        await db.db.execute(
            f"UPDATE graph_facts SET {', '.join(sets)} WHERE id = ?", params)

    await db.write_transaction(_body, op_name="provenance_update_fact")


async def _message_entity_id(db, chat_id, tg_message_id) -> str:
    """`entity_id` message-SourceRef: canonical `smart_messages.id` при наличии
    строки, иначе opaque `tg:<id>` (внутренний ID не выдаётся за Telegram)."""
    try:
        cursor = await db.db.execute(
            "SELECT id FROM smart_messages WHERE chat_id = ? AND "
            "tg_message_id = ? LIMIT 1", (int(chat_id), int(tg_message_id)))
        row = await cursor.fetchone()
        if row is not None:
            return str(int(row["id"]))
    except Exception:
        logger.debug("[provenance] smart_messages id lookup failed",
                     exc_info=True)
    return f"tg:{int(tg_message_id)}"


# ── Субъект-атрибуция (spec §4.5, FIX п.1) ──────────────────────────────────

async def resolve_subject_ref(db, chat_id: int, name,
                              *, canon=None, roster=None) -> SourceRef:
    """Резолв субъекта личного факта в SourceRef устойчивого ID (spec §4.5/D7).

    Имя/алиас — только отображение/резолв. Собираем **все** различные
    `user_id`, чьё `smart_messages.author_name` совпало с именем/канон-именем
    (casefold), одним проходом (bounded).

    * ровно один `user_id` → `resolution='resolved'` с устойчивым ID;
    * ни одного → `resolution='unresolved'` со стабильным `entity_id` по
      канон-имени (без выдуманного Telegram ID);
    * **≥2 различных `user_id` (одноимённые)** → `resolution='unresolved'` со
      стабильным `entity_id` по канон-имени: сливать людей по имени запрещено
      (SC-11/A88), произвольный выбор недопустим.

    Для self-report вызывающий обязан передать уже известный `user_id`
    говорящего (`user_source_ref`), а не резолвить по имени.

    N-MCA04A-1 (mca-04b, ADR-1027-9): `roster` — канон-имена участников
    ТЕКУЩЕГО scope (окно/диапазон пересборки). Если передан и имя в него не
    входит — резолв по БД не выполняется: «старый» одноимённый участник вне
    окна (bounded-скан ≤500 строк) больше не даёт ложный `resolved`;
    субъект остаётся явным `unresolved` (без выдуманного ID)."""
    raw = str(name or "").strip()
    canon_name = raw
    if canon is not None and raw:
        try:
            canon_name = str(canon(raw) or "").strip() or raw
        except Exception:
            canon_name = raw
    if roster is not None:
        allowed = {str(n or "").strip().casefold()
                   for n in roster if str(n or "").strip()}
        if canon_name.casefold() not in allowed:
            # Имя вне ростера scope → DB-скан не выполняется (N-1).
            return user_source_ref(chat_id, canon_name or "unknown",
                                   resolution="unresolved")
    uids = await _lookup_user_ids_by_names(db, chat_id, (raw, canon_name))
    if len(uids) == 1:
        return user_source_ref(chat_id, next(iter(uids)), resolution="resolved")
    # 0 — неизвестно; ≥2 — одноимённые. Оба случая → стабильный unresolved
    # субъект по канон-имени (никакого произвольного Telegram ID).
    return user_source_ref(chat_id, canon_name or "unknown",
                           resolution="unresolved")


async def _lookup_user_ids_by_names(db, chat_id, names) -> set[int]:
    """Все различные `user_id` по набору имён/алиасов (одним проходом).

    Пустой набор — если совпадений нет. Одноимённые дают ≥2 id → вызывающий
    трактует как неоднозначность (не сливает)."""
    keys = {str(n or "").strip().casefold() for n in (names or [])}
    keys.discard("")
    if not keys or chat_id is None:
        return set()
    found: set[int] = set()
    try:
        # SQLite LOWER() не понижает кириллицу → сравнение в Python (bounded).
        cursor = await db.db.execute(
            "SELECT user_id, author_name FROM smart_messages WHERE chat_id = ? "
            "AND user_id IS NOT NULL AND author_name IS NOT NULL AND "
            "author_name != '' ORDER BY id DESC LIMIT 500", (int(chat_id),))
        rows = await cursor.fetchall()
        for row in rows:
            if str(row["author_name"] or "").strip().casefold() in keys:
                found.add(int(row["user_id"]))
    except Exception:
        logger.debug("[provenance] subject id lookup failed", exc_info=True)
    return found


def guess_subject(fact_text, participants, canon=None):
    """Эвристика субъекта предложения факта (`subject predicate object`).

    Возвращает канон-имя участника, если факт начинается с него (или его
    канонического синонима); иначе None → `world_knowledge` (не выдумываем
    субъекта). Не является доказательством — только ключ классификации."""
    text = " ".join(str(fact_text or "").split())
    if not text:
        return None
    low = text.casefold()
    # Детерминированный порядок (D-MCA04A-6): участники могут приходить
    # множеством; при совпадении нескольких имён выбираем самое длинное
    # (конкретное) имя, затем — по алфавиту. Никакой зависимости от порядка set.
    ordered = sorted(
        {str(p).strip() for p in (participants or []) if str(p).strip()},
        key=lambda n: (-len(n), n.casefold()))
    for name in ordered:
        c = name.casefold()
        if low == c or low.startswith(c + " ") or low.startswith(c + ":"):
            return name
    first = text.split()[0]
    cf = first.casefold()
    if canon is not None:
        try:
            cf = str(canon(first) or "").strip().casefold() or cf
        except Exception:
            pass
    for name in ordered:
        if name.casefold() == cf:
            return name
    return None


def classify_assertion_kind(subject, predicate=None, *, canon=None,
                            participants=(), bot_name=None) -> str:
    """Тип утверждения (spec §4.5): biographical/preference/relation/..."""
    subj = str(subject or "").strip().casefold()
    if not subj:
        return "world_knowledge"
    if bot_name and _eq(subj, bot_name, canon):
        return "preference"
    if not _is_participant(subj, participants, canon):
        return "world_knowledge"
    pred = str(predicate or "").casefold()
    if any(marker in pred for marker in _PREFERENCE_MARKERS):
        return "preference"
    return "biographical"


def classify_attribution_method(*, origin, subject, speaker,
                                canon=None, participants=(),
                                bot_name=None) -> str:
    """Способ атрибуции (spec §4.5).

    * origin ответа бота и subject — бот → `bot_self_reply`;
    * subject не участник (общие знания/новости/этимология) → `world_knowledge`;
    * subject == speaker (автор сообщения) → `self_report` («по собственным
      словам», одно свидетельство допустимо);
    * subject — другой участник → `third_party` (атрибутированное утверждение).
    """
    if str(origin or "").strip() == "bot_self_reply":
        return "bot_self_reply"
    subj = str(subject or "").strip().casefold()
    if not subj:
        return "world_knowledge"
    if not _is_participant(subj, participants, canon):
        return "world_knowledge"
    if speaker and _eq(subj, speaker, canon):
        return "self_report"
    return "third_party"


def _eq(a, b, canon) -> bool:
    x, y = str(a or "").strip().casefold(), str(b or "").strip().casefold()
    if not x or not y:
        return False
    if x == y:
        return True
    if canon is not None:
        try:
            return str(canon(a) or "").strip().casefold() == \
                str(canon(b) or "").strip().casefold()
        except Exception:
            return False
    return False


def _is_participant(name, participants, canon) -> bool:
    if not participants:
        # Нет ростера — не выдумываем участника (world_knowledge безопаснее).
        return False
    key = str(name or "").strip().casefold()
    for p in participants:
        if _eq(key, p, canon):
            return True
    return False


# ── Восстановление старых записей (§8.2, D6) ────────────────────────────────

async def reconstruct_fact_provenance(
        db, *, fact_id: int, chat_id, fact_text: str,
        tg_message_id: int | None = None, now: int | None = None) -> dict:
    """Восстановление происхождения старой записи (§8.2/D6).

    Порядок: direct (уже есть) → exact_search (FTS) → semantic (кандидат) →
    reply/thread. **Никогда** не присваивает `original`: восстановление даёт
    `reconstructed_support` или `tentative`; при неоднозначности — `tentative`.
    Возвращает `{"origin_status", "method", "matched"}`; fail-open.

    Инертен при `MCA_EVIDENCE_RECONSTRUCTION_ENABLED=OFF` (или provenance=OFF).
    """
    result = {"origin_status": "unknown", "method": "unknown", "matched": False}
    if not reconstruction_enabled():
        return result
    try:
        obj_ref = await resolve_source_ref(
            db, graph_fact_source_ref(chat_id, fact_id))
        if obj_ref is None:
            return result
        existing = await get_evidence_links(db, obj_ref)
        if any(str(l.get("link_type")) in ("derived_from", "supports")
               for l in existing):
            # Прямо сохранённое происхождение уже есть — не переименовываем.
            return result

        ts = _now(now)
        # (2) точный поиск по тексту факта (FTS) — только кандидат.
        match = await _exact_search_message(db, chat_id, fact_text)
        if match is None and tg_message_id is not None:
            match = await _message_by_tg(db, chat_id, tg_message_id)
        if match is not None:
            entity_id = str(match["id"])
            msg_ref = await resolve_source_ref(
                db, message_source_ref(
                    chat_id=chat_id, entity_id=entity_id,
                    tg_message_id=match.get("tg_message_id")))
            if msg_ref is not None:
                await add_evidence_link(db, EvidenceLink(
                    subject_ref_id=obj_ref, source_ref_id=msg_ref,
                    link_type="supports", method="exact_search",
                    verification="tentative", independence="independent",
                    extractor_version=EXTRACTOR_VERSION,
                    basis="reconstructed exact text match",
                    checks=make_checks(author="unknown", object="unknown",
                                       time="unknown", negation="unknown",
                                       quote="unknown", joke="unknown",
                                       retelling="unknown", actuality="unknown"),
                    established_at=ts))
                # Восстановленное подтверждение ≠ original (A09/§8.2).
                await set_provenance_status(
                    db, obj_ref, origin_status="reconstructed_support",
                    now=ts)
                result.update(origin_status="reconstructed_support",
                              method="exact_search", matched=True)
                _emit_provenance_event(
                    chat_id, "provenance_reconstructed", outcome="success")
                return result
        # Нет однозначного совпадения → tentative (не выдумываем источник).
        await set_provenance_status(db, obj_ref, origin_status="tentative",
                                    now=ts)
        result.update(origin_status="tentative", method="unknown", matched=False)
        _emit_provenance_event(
            chat_id, "provenance_unresolved", outcome="skipped")
        return result
    except Exception:
        logger.warning("[provenance] reconstruction failed — fail-open "
                       "| chat=%s | fact=%s", chat_id, fact_id, exc_info=True)
        return result


async def _exact_search_message(db, chat_id, fact_text):
    """Точный поиск сообщения по FTS (bounded). None — нет однозначного."""
    text = " ".join(str(fact_text or "").split())
    if not text or chat_id is None:
        return None
    token = text[:60]
    try:
        cursor = await db.db.execute(
            "SELECT s.id, s.tg_message_id, s.user_id FROM smart_messages_fts f "
            "JOIN smart_messages s ON s.id = f.rowid "
            "WHERE f.text MATCH ? AND s.chat_id = ? LIMIT 2",
            (token, int(chat_id)))
        rows = await cursor.fetchall()
    except Exception:
        logger.debug("[provenance] exact search failed", exc_info=True)
        return None
    # Неоднозначность (2+ кандидата) → не выбираем (ambiguous → tentative).
    if len(rows) != 1:
        return None
    return dict(rows[0])


async def _message_by_tg(db, chat_id, tg_message_id):
    try:
        cursor = await db.db.execute(
            "SELECT id, tg_message_id, user_id FROM smart_messages "
            "WHERE chat_id = ? AND tg_message_id = ? LIMIT 2",
            (int(chat_id), int(tg_message_id)))
        rows = await cursor.fetchall()
    except Exception:
        return None
    if len(rows) != 1:
        return None
    return dict(rows[0])


# ── Локальные evidence → постоянные SourceRef (FIX п.5-контракт) ────────────

def _row_field(row, key, default=None):
    """Достать поле строки окна из `dict` ИЛИ `sqlite3.Row` (D-MCA04A-5).

    У `sqlite3.Row` нет `.get`, поэтому `hasattr(row, "get")` недостаточно:
    читаем по ключу с безопасным fallback."""
    if row is None:
        return default
    get = getattr(row, "get", None)
    if callable(get):
        try:
            return get(key, default)
        except Exception:
            return default
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


async def local_evidence_to_source_refs(
        db, *, chat_id, window_rows, local_numbers) -> list[dict]:
    """Перевести локальные номера evidence чанка в постоянные SourceRef.

    `window_rows` — строки окна (`smart_messages`) в том же порядке, что и
    строки промпта; локальный номер `n` адресует строку `n-1`. Возврат:
    список `{"local": n, "source_ref_id": id | None, "valid": bool}`.
    Ошибки/выход за границы — `valid=False` (без выдуманного ID). Одинаковый
    номер в разных чанках — разные WindowRef (не»один источник»)."""
    out: list[dict] = []
    rows = list(window_rows or [])
    for num in (local_numbers or []):
        try:
            n = int(num)
        except (TypeError, ValueError):
            out.append({"local": num, "source_ref_id": None, "valid": False})
            continue
        if n < 1 or n > len(rows):
            out.append({"local": n, "source_ref_id": None, "valid": False})
            continue
        row = rows[n - 1]
        row_chat = _row_field(row, "chat_id")
        if row_chat is not None and chat_id is not None \
                and int(row_chat) != int(chat_id):
            out.append({"local": n, "source_ref_id": None, "valid": False})
            continue
        tg = _row_field(row, "tg_message_id")
        entity_id = str(_row_field(row, "id", "") or "")
        if not entity_id:
            # Нет локального ID строки → не выдумываем адрес (fail-closed).
            out.append({"local": n, "source_ref_id": None, "valid": False})
            continue
        ref = await resolve_source_ref(
            db, message_source_ref(chat_id=chat_id, entity_id=entity_id,
                                   tg_message_id=tg))
        out.append({"local": n, "source_ref_id": ref, "valid": ref is not None})
    return out


def validate_layer_a_row_bounds(candidate, *, row_count: int | None,
                                message_lookup=None) -> tuple[bool, str]:
    """Проверка кандидата Layer A: evidence в границах окна/чанка и существует.

    `row_count` — число строк окна/чанка (None → границы не проверяются).
    `message_lookup(n) -> bool` — существование строки/версии (None → не
    проверяется). Возврат `(ok, reason)`; reason из закрытого набора."""
    evidence = candidate.get("evidence") if candidate else None
    if not evidence:
        return False, "no_evidence"
    if row_count is not None:
        for num in evidence:
            try:
                n = int(num)
            except (TypeError, ValueError):
                return False, "evidence_invalid"
            if n < 1 or n > int(row_count):
                return False, "evidence_out_of_range"
    if message_lookup is not None:
        for num in evidence:
            try:
                if not message_lookup(int(num)):
                    return False, "evidence_missing"
            except Exception:
                return False, "evidence_invalid"
    return True, ""


async def record_source_ids_provenance(
        db, *, fact_id: int, chat_id, source_ids,
        provenance_channel: str = "dream") -> int:
    """Типизировать `source_ids` (belief/paradigm) в `derived_from` SourceRefs.

    REUSE существующего `source_ids` (не второй store); идемпотентно (dedup
    link). Возврат — число созданных связей. No-op при provenance OFF."""
    ids = _parse_source_ids_list(source_ids)
    if not provenance_enabled() or not ids:
        return 0
    obj = await resolve_source_ref(db, graph_fact_source_ref(chat_id, fact_id))
    if obj is None:
        return 0
    await set_provenance_status(db, obj, origin_status="unknown",
                                extractor_version=EXTRACTOR_VERSION)
    await update_fact_provenance_columns(
        db, fact_id=fact_id, provenance_channel=provenance_channel,
        extractor_version=EXTRACTOR_VERSION)
    made = 0
    for sid in ids:
        if int(sid) == int(fact_id):
            continue
        ref = await resolve_source_ref(db, graph_fact_source_ref(chat_id, sid))
        if ref is None:
            continue
        await add_evidence_link(db, EvidenceLink(
            subject_ref_id=obj, source_ref_id=ref, link_type="derived_from",
            method="direct_reference", verification="verified",
            independence="independent", extractor_version=EXTRACTOR_VERSION,
            basis="belief source_ids"))
        made += 1
    return made


def _parse_source_ids_list(raw) -> list[int]:
    if raw is None:
        return []
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if not isinstance(data, list):
        return []
    out: list[int] = []
    for item in data:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            out.append(int(item))
        elif isinstance(item, str) and item.strip().lstrip("-").isdigit():
            out.append(int(item.strip()))
    return out


# ── Наблюдаемость (MCA-13, D12) ─────────────────────────────────────────────

def _emit_provenance_event(chat_id, reason_code: str, *,
                           outcome: str = "success", stage: str = "provenance",
                           component: str = "memory_provenance",
                           extra: dict | None = None) -> None:
    """Событие по контракту MCA-13 (start+outcome). Fail-open, никогда не бросает."""
    try:
        from services import mca_events
        fields = {
            "component": component,
            "stage": stage,
            "reason_code": reason_code,
            "chat_id": chat_id,
        }
        if extra:
            # Только R17-safe идентификаторные/enum-поля (клиент сам фильтрует).
            for k in ("entity_id", "model", "provider", "status"):
                if k in extra and extra[k] is not None:
                    fields[k] = extra[k]
        mca_events.emit_mca_event("memory_provenance", outcome=outcome,
                                  **fields)
    except Exception:
        logger.debug("[provenance] event emit failed (fail-open)",
                     exc_info=True)


def emit_provenance_event(chat_id, reason_code: str, **kwargs) -> None:
    """Публичная обёртка эмиссии события провенанса (REUSE mca_events)."""
    _emit_provenance_event(chat_id, reason_code, **kwargs)
