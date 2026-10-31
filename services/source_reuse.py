"""ASAP-EVIDENCE-ROUTING-01 v3 §4.5/§3 — qualified source reuse (НЕ Smart Cache).

Что переиспользуется: ПРОЧИТАННЫЙ источник, привязанный к конкретному claim
(URL|source_id + выдержка + `source_read_level` + `retrieved_at` +
`published_at`). Ответы бота, пересказы и «текст прошлой реплики» здесь не
хранятся и не отдаются никогда — это отдельный контракт (`EVOL-031`: Smart
Cache после удаления имеет только маркерный API).

Почему in-memory LRU, а не таблица: новая таблица = DDL/миграция (v41),
которых фича не требует; `services/smart_cache.py` после `EVOL-031` оставлен
как маркерный API — использовать его для источников значило бы вернуть
удалённый кеш ответов. Честное ограничение зафиксировано явно: **после
рестарта процесса reuse пуст, источник перечитывается один раз** — это обычный
fetch, а не «verified reuse».

Инварианты (§3.3):
  * `claim_key` = sha1(entity|relation|version|date|metric)[:16];
    `entity`/`relation` нормализуются существующим каноном
    `claim_envelope.normalize_proposition`;
  * разные `version`/`date`/`metric` → разные ключи (никакого «тема та же»);
  * TTL по классу claim (live_market 900 c … historical_fact 30 сут),
    hot-ключи `limits.evidence_reuse_ttl_<class>_seconds`;
  * контрдоказательство в том же диалоге → запись `contested`, как proof НЕ
    отдаётся (адресный fetch разрешён);
  * scope: приватный контекст другого чата не переиспользуется и не
    смешивается; публичный документ может переиспользоваться, но не приватная
    формулировка запроса (namespace = chat_id для всего непубличного);
  * `source_fetched ≠ verified_reuse`: reuse засчитывается только когда
    выдержка реально доставлена Writer'у (`record_delivery`).

Модуль чистый по I/O: ни сети, ни БД, ни LLM. Никогда не бросает наружу.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

# ── уровни чтения источника (§4.4 Evidence Contract) ────────────────────────
READ_LEVEL_DISCOVERED = "discovered"   # найден кандидат (URL/заголовок)
READ_LEVEL_SNIPPET = "snippet"         # есть сниппет/фрагмент выдачи
READ_LEVEL_FETCHED = "fetched"         # страница получена, но не разобрана
READ_LEVEL_PARSED = "parsed"           # текст извлечён (reader)
READ_LEVEL_SELECTED = "selected"       # выбрана релевантная часть (секция/строки)
READ_LEVELS = (READ_LEVEL_DISCOVERED, READ_LEVEL_SNIPPET, READ_LEVEL_FETCHED,
               READ_LEVEL_PARSED, READ_LEVEL_SELECTED)
#: Минимальный уровень, при котором источник считается «прочитанным».
READ_LEVEL_READ = (READ_LEVEL_FETCHED, READ_LEVEL_PARSED, READ_LEVEL_SELECTED)

# ── классы claim и TTL (§3.3) ───────────────────────────────────────────────
CLAIM_CLASS_LIVE_MARKET = "live_market"
CLAIM_CLASS_RELEASE_NEWS = "release_news"
CLAIM_CLASS_SPEC_PARAMETERS = "spec_parameters"
CLAIM_CLASS_OFFICIAL_DOCS = "official_docs"
CLAIM_CLASS_HISTORICAL_FACT = "historical_fact"

CLAIM_CLASSES = (CLAIM_CLASS_LIVE_MARKET, CLAIM_CLASS_RELEASE_NEWS,
                 CLAIM_CLASS_SPEC_PARAMETERS, CLAIM_CLASS_OFFICIAL_DOCS,
                 CLAIM_CLASS_HISTORICAL_FACT)

#: Заводские TTL (секунды). Hot-ключ:
#: `limits.evidence_reuse_ttl_<class>_seconds` (переопределяемо эксплуатацией).
DEFAULT_TTL_SECONDS: dict[str, int] = {
    CLAIM_CLASS_LIVE_MARKET: 900,                    # 15 мин
    CLAIM_CLASS_RELEASE_NEWS: 6 * 3600,              # 6 ч
    CLAIM_CLASS_SPEC_PARAMETERS: 7 * 86400,          # 7 сут
    CLAIM_CLASS_OFFICIAL_DOCS: 14 * 86400,           # 14 сут
    CLAIM_CLASS_HISTORICAL_FACT: 30 * 86400,         # 30 сут
}

#: Отношение claim → класс свежести (закрытая таблица, не эвристика темы).
RELATION_TO_CLASS: dict[str, str] = {
    "price": CLAIM_CLASS_LIVE_MARKET,
    "availability": CLAIM_CLASS_LIVE_MARKET,
    "exists": CLAIM_CLASS_RELEASE_NEWS,
    "version": CLAIM_CLASS_RELEASE_NEWS,
    "event": CLAIM_CLASS_RELEASE_NEWS,
    "date": CLAIM_CLASS_RELEASE_NEWS,
    "comparison": CLAIM_CLASS_RELEASE_NEWS,
    "spec": CLAIM_CLASS_SPEC_PARAMETERS,
    "api": CLAIM_CLASS_OFFICIAL_DOCS,
    "doc": CLAIM_CLASS_OFFICIAL_DOCS,
    "historical": CLAIM_CLASS_HISTORICAL_FACT,
}
DEFAULT_CLAIM_CLASS = CLAIM_CLASS_RELEASE_NEWS

#: Максимум записей LRU (hot `limits.evidence_reuse_max_entries`).
MAX_ENTRIES_DEFAULT = 256


def evidence_reuse_enabled() -> bool:
    """Kill-switch `EVIDENCE_REUSE_ENABLED` (env-only ClassVar, default ON;
    резолв per-call). OFF → lookup всегда miss, записи не создаются (прежнее
    поведение: обычный fetch)."""
    try:
        return bool(getattr(settings, "EVIDENCE_REUSE_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def _max_entries() -> int:
    try:
        value = int(hot.get("limits.evidence_reuse_max_entries",
                            MAX_ENTRIES_DEFAULT))
    except Exception:      # pragma: no cover - защитная ветка
        return MAX_ENTRIES_DEFAULT
    return value if value > 0 else MAX_ENTRIES_DEFAULT


def ttl_seconds(claim_class: str) -> int:
    """TTL класса claim: hot-ключ → заводской дефолт (мусор → дефолт)."""
    cls = str(claim_class or "").strip().lower() or DEFAULT_CLAIM_CLASS
    default = DEFAULT_TTL_SECONDS.get(cls, DEFAULT_TTL_SECONDS[DEFAULT_CLAIM_CLASS])
    try:
        value = int(hot.get(f"limits.evidence_reuse_ttl_{cls}_seconds", default))
    except Exception:      # pragma: no cover - защитная ветка
        return default
    return value if value > 0 else default


# ── claim key (§3.2) ────────────────────────────────────────────────────────
def _normalize(value: str | None) -> str:
    """Канон текста существующим нормализатором (whitespace/пунктуация).

    `claim_envelope.normalize_proposition` — единственный канон проекта; при
    его недоступности (не должно случаться) — консервативный lower/strip."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        from services.claim_envelope import normalize_proposition
        normalized = normalize_proposition(text)
        if normalized:
            return str(normalized)
    except Exception:      # pragma: no cover - защитная ветка
        pass
    return " ".join(text.lower().split())


@dataclass(frozen=True)
class ClaimKey:
    """Нормализованный ключ claim: сущность+отношение+версия+дата+метрика.

    «Тема та же» или совпадение названия продукта переиспользование НЕ
    разрешает: любая различающаяся компонента даёт другой ключ.

    ЕДИНЫЙ КАНОН: если в процессе есть `services/evidence_policy.ClaimKey`
    (policy-слой владеет §3.2), ключ/дайджест делегируются ему — второй
    канон привёл бы к тому, что reuse и coverage считали бы разные ключи для
    одного тезиса."""

    entity: str
    relation: str
    version: str = ""
    date: str = ""
    metric: str = ""

    def canonical(self) -> str:
        policy = _policy_claim_key_class()
        if policy is not None:
            try:
                instance = policy(entity=self.entity, relation=self.relation,
                                  version=self.version, date=self.date,
                                  metric=self.metric)
                return "|".join((instance.entity, instance.relation,
                                 instance.version, instance.date,
                                 instance.metric))
            except Exception:      # pragma: no cover - защитная ветка
                pass
        return "|".join((_normalize(self.entity), _normalize(self.relation),
                         _normalize(self.version), _normalize(self.date),
                         _normalize(self.metric)))

    def key(self) -> str:
        return hashlib.sha1(self.canonical().encode("utf-8")).hexdigest()[:16]

    @property
    def claim_class(self) -> str:
        return claim_class_for(self.relation)

    def as_dict(self) -> dict:
        return {"claim_key": self.key(), "entity": self.entity,
                "relation": self.relation, "version": self.version,
                "date": self.date, "metric": self.metric}


_POLICY_CLAIM_KEY_CLASS = None
_POLICY_CLAIM_KEY_CHECKED = False


def _policy_claim_key_class():
    """Единый канон claim-key из policy-модуля (ленивый import, кэш)."""
    global _POLICY_CLAIM_KEY_CLASS, _POLICY_CLAIM_KEY_CHECKED
    if _POLICY_CLAIM_KEY_CHECKED:
        return _POLICY_CLAIM_KEY_CLASS
    _POLICY_CLAIM_KEY_CHECKED = True
    try:      # pragma: no branch - модуль может отсутствовать в изоляции
        from services.evidence_policy import ClaimKey as PolicyClaimKey
        _POLICY_CLAIM_KEY_CLASS = PolicyClaimKey
    except Exception:
        _POLICY_CLAIM_KEY_CLASS = None
    return _POLICY_CLAIM_KEY_CLASS


def claim_key(entity: str, relation: str, version: str = "", date: str = "",
              metric: str = "") -> ClaimKey:
    """Построить ключ claim (не бросает).

    Возвращается ЭКЗЕМПЛЯР единого канона (policy-класс, если он есть), чтобы
    reuse/lookup/coverage и policy-слой использовали один и тот же дайджест."""
    policy = _policy_claim_key_class()
    if policy is not None:
        try:
            return policy(entity=str(entity or ""),
                          relation=str(relation or ""),
                          version=str(version or ""), date=str(date or ""),
                          metric=str(metric or ""))
        except Exception:      # pragma: no cover - защитная ветка
            pass
    return ClaimKey(entity=str(entity or ""), relation=str(relation or ""),
                    version=str(version or ""), date=str(date or ""),
                    metric=str(metric or ""))


def claim_key_from_mapping(raw) -> ClaimKey | None:
    """ClaimKey из dict/объекта L1-аннотации (`external_claims[]`).

    Невалидный/пустой элемент → None (правило §1.6: элемент отбрасывается,
    пустой список не ломает решение политики). Чужой claim-key объект (policy
    `ClaimKey`) проходит БЕЗ пересборки — единый канон сохраняется."""
    if raw is None:
        return None
    if isinstance(raw, ClaimKey):
        return raw
    try:
        if isinstance(raw, dict):
            entity = str(raw.get("entity") or "").strip()
            relation = str(raw.get("relation") or "").strip()
            if not entity or not relation:
                return None
            return claim_key(entity, relation,
                             raw.get("version") or "", raw.get("date") or "",
                             raw.get("metric") or "")
        entity = str(getattr(raw, "entity", "") or "").strip()
        relation = str(getattr(raw, "relation", "") or "").strip()
        if not entity or not relation:
            return None
        if callable(getattr(raw, "key", None)):
            # Уже канонический объект (policy ClaimKey) — не пересобираем.
            return raw
        return claim_key(entity, relation,
                         getattr(raw, "version", "") or "",
                         getattr(raw, "date", "") or "",
                         getattr(raw, "metric", "") or "")
    except Exception:      # pragma: no cover - защитная ветка
        return None


def claim_class_for(relation: str) -> str:
    """Класс свежести по отношению claim (закрытая таблица)."""
    return RELATION_TO_CLASS.get(str(relation or "").strip().lower(),
                                 DEFAULT_CLAIM_CLASS)


# ── запись источника ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SourceRecord:
    """Прочитанный источник, привязанный к claim (§3.1)."""

    claim: ClaimKey
    url: str = ""
    source_id: str = ""
    snippet: str = ""
    read_level: str = READ_LEVEL_FETCHED
    source_kind: str = ""
    retrieved_at: float = 0.0
    published_at: str = ""
    published_at_source: str = ""
    claim_class: str = DEFAULT_CLAIM_CLASS
    ttl_seconds: int = 0
    scope: str = "public"        # public | chat
    chat_id: int | None = None
    contested: bool = False
    delivered_chars: int = 0
    hits: int = 0
    full_source_pointer: dict = field(default_factory=dict)

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - float(self.retrieved_at or 0.0))

    def expired(self, *, now: float | None = None) -> bool:
        moment = time.time() if now is None else float(now)
        ttl = int(self.ttl_seconds or ttl_seconds(self.claim_class))
        return (moment - float(self.retrieved_at or 0.0)) >= ttl

    @property
    def verified_reuse(self) -> bool:
        """Reuse = proof только когда выдержка реально доставлена."""
        return bool(self.delivered_chars > 0) and not self.contested

    def as_evidence_fields(self) -> dict:
        """Поля EvidenceSource (§4.4): identity + read level + указатель."""
        return {
            "claim_keys": [self.claim.key()],
            "source_read_level": self.read_level,
            "source_id": self.source_id,
            "url": self.url,
            "source_kind": self.source_kind,
            "published_at": self.published_at,
            "published_at_source": self.published_at_source,
            "retrieved_at": int(self.retrieved_at or 0),
            "full_source_pointer": dict(self.full_source_pointer or {}),
            "reuse": self.verified_reuse,
        }


# ── in-memory LRU ──────────────────────────────────────────────────────────
_LOCK = threading.RLock()
_STORE: "OrderedDict[str, SourceRecord]" = OrderedDict()
_STATS: dict[str, int] = {
    "lookups": 0, "hits": 0, "misses": 0, "expired": 0, "contested_hits": 0,
    "scope_blocked": 0, "stored": 0, "evicted": 0, "delivered": 0,
    #: внутренние сбои кеша (fail-open не должен быть невидимым)
    "errors": 0,
}


def _bump(axis: str, value: int = 1) -> None:
    """Инкремент счётчика без исключений (наблюдаемость fail-open)."""
    try:
        with _LOCK:
            _STATS[axis] = int(_STATS.get(axis, 0)) + int(value)
    except Exception:      # pragma: no cover - защитная ветка
        pass


def _namespace(claim: ClaimKey, scope: str, chat_id: int | None) -> str:
    """Ключ хранения: приватный контекст не смешивается между чатами.

    Публичный документ (`scope="public"`) переиспользуется на основании самого
    источника; приватная формулировка/история — только внутри своего чата."""
    base = claim.key()
    if str(scope or "public") != "public":
        return f"{base}@chat:{chat_id if chat_id is not None else 'unknown'}"
    return f"{base}@public"


def claim_class_of(claim) -> str:
    """Класс свежести для claim-объекта любого канона (policy/local)."""
    try:
        explicit = getattr(claim, "claim_class", None)
        if isinstance(explicit, str) and explicit:
            return explicit
    except Exception:      # pragma: no cover - защитная ветка
        pass
    return claim_class_for(str(getattr(claim, "relation", "") or ""))


def store(claim: ClaimKey, *, url: str = "", source_id: str = "",
          snippet: str = "", read_level: str = READ_LEVEL_FETCHED,
          source_kind: str = "", published_at: str = "",
          published_at_source: str = "", scope: str = "public",
          chat_id: int | None = None,
          full_source_pointer: dict | None = None,
          retrieved_at: float | None = None) -> SourceRecord | None:
    """Записать прочитанный источник (fail-open: OFF/мусор → None)."""
    if not evidence_reuse_enabled():
        return None
    try:
        key = _namespace(claim, scope, chat_id)
        claim_class = claim_class_of(claim)
        record = SourceRecord(
            claim=claim, url=str(url or ""), source_id=str(source_id or ""),
            snippet=str(snippet or ""),
            read_level=read_level if read_level in READ_LEVELS
            else READ_LEVEL_FETCHED,
            source_kind=str(source_kind or ""),
            retrieved_at=float(retrieved_at if retrieved_at is not None
                               else time.time()),
            published_at=str(published_at or ""),
            published_at_source=str(published_at_source or ""),
            claim_class=claim_class, ttl_seconds=ttl_seconds(claim_class),
            scope=str(scope or "public"), chat_id=chat_id,
            full_source_pointer=dict(full_source_pointer or {}))
        with _LOCK:
            limit = _max_entries()
            if key in _STORE:
                _STORE.move_to_end(key)
            _STORE[key] = record
            _STATS["stored"] += 1
            while len(_STORE) > limit:
                _STORE.popitem(last=False)
                _STATS["evicted"] += 1
        return record
    except Exception:      # pragma: no cover - защитная ветка
        _bump("errors")
        logger.debug("[source_reuse] store failed", exc_info=True)
        return None


def lookup(claim: ClaimKey, *, scope: str = "public",
           chat_id: int | None = None, bypass: bool = False,
           now: float | None = None) -> SourceRecord | None:
    """Найти свежую запись для claim. miss/expired/contested → None.

    ``bypass=True`` — явная просьба «обнови/проверь заново» (§3.3): запись НЕ
    используется и удаляется, чтобы не отдавать устаревшее как proof."""
    if not evidence_reuse_enabled():
        return None
    try:
        key = _namespace(claim, scope, chat_id)
        with _LOCK:
            _STATS["lookups"] += 1
            record = _STORE.get(key)
            if record is None:
                _STATS["misses"] += 1
                return None
            if bypass:
                _STORE.pop(key, None)
                _STATS["misses"] += 1
                return None
            if record.expired(now=now):
                _STORE.pop(key, None)
                _STATS["expired"] += 1
                _STATS["misses"] += 1
                return None
            if record.contested:
                _STATS["contested_hits"] += 1
                _STATS["misses"] += 1
                return None
            if record.read_level not in READ_LEVEL_READ:
                # Кандидат/сниппет прочитанным источником не считается.
                _STATS["misses"] += 1
                return None
            _STORE.move_to_end(key)
            record = replace(record, hits=record.hits + 1)
            _STORE[key] = record
            _STATS["hits"] += 1
            return record
    except Exception:      # pragma: no cover - защитная ветка
        _bump("errors")
        logger.debug("[source_reuse] lookup failed", exc_info=True)
        return None


def mark_contested(claim: ClaimKey, *, scope: str = "public",
                   chat_id: int | None = None, source_id: str = "") -> bool:
    """Пометить запись спорной (контрдоказательство в том же диалоге).

    Спорная запись не отдаётся как proof; адресный fetch разрешён (§3.3)."""
    if not evidence_reuse_enabled():
        return False
    try:
        key = _namespace(claim, scope, chat_id)
        with _LOCK:
            record = _STORE.get(key)
            if record is None:
                return False
            if source_id and record.source_id and record.source_id != source_id:
                return False
            _STORE[key] = replace(record, contested=True)
            return True
    except Exception:      # pragma: no cover - защитная ветка
        return False


def record_delivery(claim: ClaimKey, delivered_chars: int, *,
                    scope: str = "public", chat_id: int | None = None) -> bool:
    """Отметить фактическую доставку выдержки Writer'у (`source_fetched ≠
    verified_reuse`, §3.4)."""
    if not evidence_reuse_enabled():
        return False
    try:
        chars = max(0, int(delivered_chars or 0))
    except (TypeError, ValueError):
        return False
    if chars <= 0:
        return False
    try:
        key = _namespace(claim, scope, chat_id)
        with _LOCK:
            record = _STORE.get(key)
            if record is None:
                return False
            _STORE[key] = replace(record, delivered_chars=chars)
            _STATS["delivered"] += 1
            return True
    except Exception:      # pragma: no cover - защитная ветка
        return False


def reuse_line(record: SourceRecord) -> str:
    """Машинная строка пакета: `reuse: <claim_key> | <source_id> | age=…`."""
    age = int(record.age_seconds)
    return (f"reuse: {record.claim.key()} | {record.source_id or record.url}"
            f" | age={age}s | read={record.read_level}")


def clear() -> None:
    """Полный сброс (рестарт процесса / тесты)."""
    with _LOCK:
        _STORE.clear()


def stats() -> dict:
    """Счётчики reuse (§4.7/сценарий 46: числа, не текст)."""
    with _LOCK:
        snapshot = dict(_STATS)
        snapshot["entries"] = len(_STORE)
    snapshot["enabled"] = evidence_reuse_enabled()
    return snapshot


def reset_stats() -> None:
    """Обнулить счётчики (тесты/наблюдение на прогон)."""
    with _LOCK:
        for key in _STATS:
            _STATS[key] = 0


# ── claim → source linkage / coverage / delivery ────────────────────────────
def read_level_from_payload(payload, *, search_candidate: bool = False) -> str:
    """Уровень чтения по payload инструмента (§4.4).

    ``fetch_article`` ok → `selected` (выбрана выдержка) или `parsed`
    (текст целиком); ошибка → "" (источник не прочитан). Поисковая выдача —
    только кандидаты: `snippet`/`discovered`."""
    if not isinstance(payload, dict):
        return ""
    if search_candidate:
        return READ_LEVEL_SNIPPET if str(payload.get("snippet") or "").strip() \
            else READ_LEVEL_DISCOVERED
    if str(payload.get("status") or "").lower() != "ok":
        return ""
    explicit = str(payload.get("read_level") or "")
    if explicit in READ_LEVELS:
        return explicit
    if payload.get("excerpt"):
        return READ_LEVEL_SELECTED
    if payload.get("markdown"):
        return READ_LEVEL_PARSED
    return READ_LEVEL_FETCHED


def link_claim_source(claim: ClaimKey, payload, *, role: str = "",
                      relevance=None,
                      full_source_pointer: dict | None = None) -> dict:
    """Пара `claim → source` для пакета/coverage (§4.4/§4.5).

    Возвращает R17-safe запись (без текста страницы): ключ claim, identity
    источника, уровень чтения, даты, роль доказательства."""
    payload = payload if isinstance(payload, dict) else {}
    pointer = full_source_pointer or payload.get("full_source_pointer") or {}
    return {
        "claim_key": claim.key(),
        "entity": claim.entity,
        "relation": claim.relation,
        "source_id": str(payload.get("source_id") or ""),
        "url": str(payload.get("url") or ""),
        "read_level": read_level_from_payload(payload),
        "role": str(role or ""),
        "relevance": getattr(relevance, "role", "") if relevance is not None
        else "",
        "supports": bool(getattr(relevance, "role", "") == "supports")
        if relevance is not None else False,
        "contradicts": bool(getattr(relevance, "role", "") == "contradicts")
        if relevance is not None else False,
        "published_at": str(payload.get("published_at") or ""),
        "published_at_source": str(payload.get("published_at_source") or ""),
        "full_source_pointer": dict(pointer or {}),
    }


def build_coverage(required_claim_keys, links) -> dict:
    """Coverage пакета: какие обязательные claim реально покрыты источником.

    Покрытие требует доставленного прочитанного источника (не кандидата):
    `read_level ∈ fetched|parsed|selected` и непустой `source_id`/`url`."""
    required: list[str] = []
    for item in required_claim_keys or ():
        key = (item.key() if callable(getattr(item, "key", None))
               else str(item or ""))
        if key and key not in required:
            required.append(key)
    covered: list[str] = []
    for link in links or ():
        if not isinstance(link, dict):
            continue
        key = str(link.get("claim_key") or "")
        if not key or key in covered or key not in required:
            continue
        if str(link.get("read_level") or "") not in READ_LEVEL_READ:
            continue
        if not (link.get("source_id") or link.get("url")):
            continue
        covered.append(key)
    missing = [key for key in required if key not in covered]
    ratio = (len(covered) / len(required)) if required else 1.0
    return {"required_claim_keys": required, "covered": covered,
            "missing": missing, "coverage_ratio": round(ratio, 4)}


def delivery_state(*, source_fetched: bool, delivered_chars: int,
                   reused: bool = False) -> str:
    """Различить `source_fetched` / `evidence_delivered_to_writer` / reuse.

    Значения: `not_fetched`, `fetched_not_delivered`, `delivered`,
    `verified_reuse` (§4.5: fetch ≠ delivery ≠ verified)."""
    if reused and int(delivered_chars or 0) > 0:
        return "verified_reuse"
    if not source_fetched:
        return "not_fetched"
    if int(delivered_chars or 0) <= 0:
        return "fetched_not_delivered"
    return "delivered"


__all__ = [
    "READ_LEVEL_DISCOVERED", "READ_LEVEL_SNIPPET", "READ_LEVEL_FETCHED",
    "READ_LEVEL_PARSED", "READ_LEVEL_SELECTED", "READ_LEVELS", "READ_LEVEL_READ",
    "CLAIM_CLASSES", "CLAIM_CLASS_LIVE_MARKET", "CLAIM_CLASS_RELEASE_NEWS",
    "CLAIM_CLASS_SPEC_PARAMETERS", "CLAIM_CLASS_OFFICIAL_DOCS",
    "CLAIM_CLASS_HISTORICAL_FACT", "DEFAULT_TTL_SECONDS", "RELATION_TO_CLASS",
    "DEFAULT_CLAIM_CLASS", "ClaimKey", "SourceRecord", "claim_key",
    "claim_key_from_mapping", "claim_class_for", "claim_class_of",
    "ttl_seconds",
    "evidence_reuse_enabled", "store", "lookup", "mark_contested",
    "record_delivery", "reuse_line", "clear", "stats", "reset_stats",
    "read_level_from_payload", "link_claim_source", "build_coverage",
    "delivery_state",
]
