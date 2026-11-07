"""EPIC-MEMORY-COGNITIVE-02 / MEMORY-02 (слайс A) — каноническая идентичность.

Источник: `plans/features/memory-cognitive-02/contracts.md` (rev3) §1.2
(порядок разрешения), §1.2.1 (засев `B2-0` и инвариант уникальности),
§1.2.2 (ограниченная генерация casefold-кандидатов), §1.2.3 (один слот имени
и разные типы), §1.4.1 (единственная точка создания узла), §5.1 (`v43`),
§5.3 (`B2-0`). Инвентаризация — `audit-a0.md`.

Что здесь есть:

* **`resolve_entity`** — read-only фасад разрешения идентичности. Ничего не
  пишет (ID-1): ни узлов, ни redirect-строк, ни evidence. Засев — отдельный
  шаг бэкфилла (`seed_self_identity`, §1.2.1 / `B2-0`).
* **`seed_self_identity`** — идемпотентный засев self-строк `tg_user` по
  существующим данным (`users_meta`, действующий alias-каскад,
  `smart_messages.author_name`). Никогда не использует `INSERT OR REPLACE`:
  узел, закреплённый за другим uid, даёт `identity_seed_node_conflict`, а не
  перезапись `stable_value` (§1.2.1, ID-11, EVAL-04).
* **`resolve_or_create_node`** — единственная точка **создания** узла для
  писателей W1–W6 (§1.4.1). Часть B перевела на неё реальных создателей узлов
  (`summary_memory`): W1 (real-time факт) и W2 (`_write_graph_triplets`,
  `commit=False` — узлы и рёбра одной транзакцией). Остальные пути инвентаря
  §1.4.1 на этой линии узлов не создают вообще (проверено `git grep
  upsert_node` и тестом `test_no_direct_upsert_node_in_any_writer`): W3
  (`dream_worker`, beliefs), W4 (`lore_worker`/`lore_compiler_service`), W5
  (`chat_lore` → `user_memory`, self-факт `summary_memory::memorize_self_reply`),
  W6 (`memory_maintenance`, `memory_rebuild`, `chat_migration`) пишут только
  факты/строки и не материализуют сущности — дублей узлов там не возникает, а
  прямой `upsert_node` запрещён структурно.
* **DDL владельца** таблицы `mca_entity_canonical` (`v43`): миграция в
  `services/database.py` применяет ровно эти выражения, второй копии нет.

Границы (проверяется ревью): нет второго словаря алиасов, нет второй таблицы
сущностей, нет UUID-идентичности, нет `UNIQUE` по casefold(name), нет полного
скана `nodes` (только диапазон `[C, C+1 codepoint)` с `LIMIT`), casefold —
только генерация кандидатов и **никогда** не слияние (ID-4).

Гейт `MCA_MEMORY_IDENTITY_ENABLED` (реестр `services/mca_gates.py`, default
**OFF**, per-chat через каталоговый `flags.memory_identity_enabled`):
OFF → ровно сегодняшний точный путь по имени, новые таблицы не читаются и не
пишутся (§1.7). ON → правила 1–7 §1.2.

`scope.entity_type` вне четырёх разрешённых значений — ошибка типизированной
границы (`memory_contracts.EntityScope` бросает `ValueError`, MEMORY-01):
такой вызов не становится `new` и не резолвится в чужой тип. Остальные
«rejected»-условия §1.2 п.7 (пустой/пробельный mention, mention > 200
символов) возвращаются честным `rejected`.
"""
from __future__ import annotations

import dataclasses
import logging
import sqlite3
import time
import unicodedata
from typing import Any, Iterable, Mapping

from services import memory_contracts as mc
from services.mca_gates import memory_identity_enabled

logger = logging.getLogger(__name__)

#: Имя аддитивной таблицы идентичности (миграция `v43`).
ENTITY_CANONICAL_TABLE = "mca_entity_canonical"
#: Стабильное имя шага миграции (книга `schema_migrations`).
ENTITY_CANONICAL_MIGRATION_STEP_NAME = "entity_canonical_v43"

#: DDL владельца таблицы — применяет миграция `v43` (`services/database.py`)
#: и тесты. `CREATE ... IF NOT EXISTS`: повторный прогон — no-op,
#: `nodes`/`edges`/`graph_facts` не меняются, `ALTER` не нужен (§5.1).
ENTITY_CANONICAL_DDL_SQLITE: tuple[str, ...] = (
    f"CREATE TABLE IF NOT EXISTS {ENTITY_CANONICAL_TABLE} ("
    "chat_id           INTEGER NOT NULL, "
    "entity_type       TEXT NOT NULL, "
    "member_node_id    INTEGER NOT NULL, "      # nodes.id как есть
    "canonical_node_id INTEGER NOT NULL, "      # = member для resolution='self'
    "resolution        TEXT NOT NULL, "         # self|alias|merged
    "stable_kind       TEXT, "                  # 'tg_user' | NULL
    "stable_value      TEXT, "                  # '428494' | NULL
    "method            TEXT NOT NULL, "         # alias_map|explicit_evidence|manual_admin
    "evidence_ref_id   INTEGER, "               # mca_source_refs.source_ref_id
    "confidence        TEXT NOT NULL, "         # confirmed|tentative
    "status            TEXT NOT NULL DEFAULT 'active', "  # active|revoked
    "created_at        INTEGER NOT NULL, "
    "updated_at        INTEGER NOT NULL, "
    "PRIMARY KEY (chat_id, entity_type, member_node_id))",
)

#: Индексы владельца: частичный UNIQUE даёт инвариант ID-11 (один узел ↔ не
#: более одной активной устойчивой идентичности и один `stable_value` ↔ ровно
#: один узел), второй — чтение схлопывания member→canonical (§1.4).
ENTITY_CANONICAL_INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_mca_entity_canonical_stable "
    f"ON {ENTITY_CANONICAL_TABLE} "
    "(chat_id, entity_type, stable_kind, stable_value) "
    "WHERE status='active' AND stable_kind IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_mca_entity_canonical_canonical "
    f"ON {ENTITY_CANONICAL_TABLE} (chat_id, canonical_node_id)",
)

# ── закрытые строковые значения таблицы (§5.1) ─────────────────────────────
RESOLUTION_SELF = "self"
RESOLUTION_ALIAS = "alias"
RESOLUTION_MERGED = "merged"

STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"

STABLE_KIND_TG_USER = "tg_user"

METHOD_ALIAS_MAP = "alias_map"
METHOD_EXPLICIT_EVIDENCE = "explicit_evidence"
METHOD_MANUAL_ADMIN = "manual_admin"

CONFIDENCE_CONFIRMED = "confirmed"
CONFIDENCE_TENTATIVE = "tentative"

# ── reason-коды (§1.2 / §1.2.1 / §1.2.2 / §1.2.3) ──────────────────────────
REASON_STABLE_IDENTITY = "stable_identity"
REASON_IDENTITY_DUPLICATE_CLAIM = "identity_duplicate_claim"
REASON_IDENTITY_NOT_SEEDED = "identity_not_seeded"
REASON_ALIAS_MAP = "alias_map"
REASON_EXACT_NAME = "exact_name"
REASON_CASEFOLD_UNIQUE = "casefold_unique"
REASON_CASEFOLD_MULTIPLE = "casefold_multiple"
REASON_CASEFOLD_OVERFLOW = "casefold_prefix_overflow"
REASON_REDIRECT_FLATTENED = "redirect_chain_flattened"
REASON_REDIRECT_CYCLE = "redirect_cycle_detected"
REASON_TYPE_CONFLICT = "type_conflict_single_slot"
REASON_IDENTITY_NODE_CONFLICT = "identity_node_conflict"
REASON_EMPTY_MENTION = "empty_mention"
REASON_MENTION_TOO_LONG = "mention_too_long"
REASON_INVALID_ENTITY_TYPE = "invalid_entity_type"
REASON_NO_MATCH = "no_match"
REASON_CREATED = "created"

#: Засев `B2-0` (§1.2.1, §5.3).
SEED_SEEDED = "seeded"
SEED_ALREADY_PINNED = "identity_seed_already_pinned"
SEED_MISSING = "identity_seed_missing"
SEED_AMBIGUOUS = "identity_seed_ambiguous"
SEED_NODE_CONFLICT = "identity_seed_node_conflict"
SEED_REVOKED = "identity_seed_skipped_revoked"

#: `LIMIT` ограниченной генерации кандидатов: 32 + 1 для детекта переполнения.
ENTITY_CASEFOLD_SCAN_LIMIT = mc.ENTITY_CASEFOLD_MAX_ROWS + 1
#: Единственный диапазонный запрос правила 4 (§1.2.2): «начинается с `C`» в
#: BINARY-сравнении SQLite (`[C, C+1 codepoint)`), `LIMIT` — обязателен.
CASEFOLD_SCAN_SQL = (
    "SELECT id, entity_name, entity_type FROM nodes "
    "WHERE chat_id = ? AND entity_name >= ? AND entity_name < ? "
    "AND entity_type = ? ORDER BY entity_name LIMIT ?"
)
#: Сколько вариантов неоднозначности отдаётся наружу (не «дочитывать всё»).
_AMBIGUOUS_PREVIEW_MAX = 8
#: Потолок длины цепочки redirect при чтении (данные не «выпрямляются»).
_REDIRECT_MAX_STEPS = 32
#: Потолок member-узлов, перечисляемых в `legacy_ids`/`aliases` одного ref.
_LEGACY_PREVIEW_MAX = 64


# ── вспомогательное: доступ к строкам соединения ───────────────────────────

async def _fetchall(db, sql: str, params: Iterable[Any] = ()) -> list[Any]:
    cursor = await db.db.execute(sql, tuple(params))
    return list(await cursor.fetchall())


async def _fetchone(db, sql: str, params: Iterable[Any] = ()):
    cursor = await db.db.execute(sql, tuple(params))
    return await cursor.fetchone()


def _value(row, key: str, index: int):
    """Значение колонки из `aiosqlite.Row` либо кортежа."""
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return row[index]


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", str(text))


def _fold(text: str) -> str:
    """Сравнительный ключ кандидатов: NFC + trim + casefold (только сравнение)."""
    return _nfc(text).strip().casefold()


def _emit(event_name: str, *, outcome: str = "success", **fields: Any) -> None:
    """Наблюдаемость без текстов чата (R17); телеметрия не рвёт резолв."""
    try:
        from services import mca_events
        mca_events.emit_mca_event(event_name, outcome=outcome,
                                  component="entity_resolver", **fields)
    except Exception:          # pragma: no cover — fail-open
        logger.debug("[entity_resolver] event failed | %s", event_name,
                     exc_info=True)


# ── узлы и канонические строки ─────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class _NodeRow:
    node_id: int
    entity_name: str
    entity_type: str


async def _node_by_exact_name(db, chat_id: int, name: str) -> _NodeRow | None:
    """Точное имя байт-в-байт (legacy-путь `upsert_node`)."""
    row = await _fetchone(
        db,
        "SELECT id, entity_name, entity_type FROM nodes "
        "WHERE chat_id = ? AND entity_name = ?",
        (chat_id, name),
    )
    if row is None:
        return None
    return _NodeRow(int(_value(row, "id", 0)),
                    str(_value(row, "entity_name", 1)),
                    str(_value(row, "entity_type", 2)))


async def _node_by_id(db, node_id: int) -> _NodeRow | None:
    row = await _fetchone(
        db,
        "SELECT id, entity_name, entity_type FROM nodes WHERE id = ?",
        (node_id,),
    )
    if row is None:
        return None
    return _NodeRow(int(_value(row, "id", 0)),
                    str(_value(row, "entity_name", 1)),
                    str(_value(row, "entity_type", 2)))


def _casefold_bounds(mention: str) -> list[tuple[str, str]]:
    """Диапазоны `[C, C+1 codepoint)` для первого графемного префикса (§1.2.2).

    `LIKE` не используется: `NOCASE` в SQLite не сворачивает кириллицу.
    """
    text = _nfc(mention).strip()
    if not text:
        return []
    prefix = text[:max(1, int(mc.ENTITY_CASEFOLD_MIN_PREFIX))]
    variants: list[str] = []
    for candidate in (prefix, prefix.upper(), prefix.lower(), prefix.casefold()):
        if candidate and candidate not in variants:
            variants.append(candidate)
    bounds: list[tuple[str, str]] = []
    for candidate in variants:
        last = candidate[-1]
        if ord(last) >= 0x10FFFF:
            continue
        upper = candidate[:-1] + chr(ord(last) + 1)
        if (candidate, upper) not in bounds:
            bounds.append((candidate, upper))
    return bounds


async def _casefold_scan(db, chat_id: int, entity_type: str, mention: str
                         ) -> tuple[list[_NodeRow], list[_NodeRow]]:
    """Ограниченная генерация casefold-кандидатов (§1.2.2).

    Возвращает `(совпадения, строки переполненного префикса)`. Для каждого
    варианта префикса — ровно один диапазонный SELECT по индексу
    `(chat_id, entity_name)` с `LIMIT 33`. Совпадение проверяется в Python
    (`casefold(trim(NFC(name)))`); полного скана и «дочитывания всего» нет.
    """
    matches: list[_NodeRow] = []
    seen: set[int] = set()
    overflow_rows: list[_NodeRow] = []
    for lower, upper in _casefold_bounds(mention):
        rows = await _fetchall(
            db,
            CASEFOLD_SCAN_SQL,
            (chat_id, lower, upper, entity_type, ENTITY_CASEFOLD_SCAN_LIMIT),
        )
        if len(rows) >= ENTITY_CASEFOLD_SCAN_LIMIT:
            overflow_rows.extend(
                _NodeRow(int(_value(row, "id", 0)),
                         str(_value(row, "entity_name", 1)),
                         str(_value(row, "entity_type", 2)))
                for row in rows[:_AMBIGUOUS_PREVIEW_MAX])
        for row in rows:
            node = _NodeRow(int(_value(row, "id", 0)),
                            str(_value(row, "entity_name", 1)),
                            str(_value(row, "entity_type", 2)))
            if (node.node_id in seen
                    or _fold(node.entity_name) != _fold(mention)):
                continue
            seen.add(node.node_id)
            matches.append(node)
    deduped_overflow: list[_NodeRow] = []
    overflow_seen: set[int] = set()
    for node in overflow_rows:
        if node.node_id in overflow_seen:
            continue
        overflow_seen.add(node.node_id)
        deduped_overflow.append(node)
    return matches, deduped_overflow


async def _active_rows_for_member(db, chat_id: int, entity_type: str,
                                  node_id: int) -> list[Any]:
    return await _fetchall(
        db,
        f"SELECT * FROM {ENTITY_CANONICAL_TABLE} "
        "WHERE chat_id = ? AND entity_type = ? AND member_node_id = ? "
        "AND status = ?",
        (chat_id, entity_type, node_id, STATUS_ACTIVE),
    )


async def _active_self_rows(db, chat_id: int, entity_type: str,
                            stable_value: str) -> list[Any]:
    return await _fetchall(
        db,
        f"SELECT * FROM {ENTITY_CANONICAL_TABLE} "
        "WHERE chat_id = ? AND entity_type = ? AND stable_kind = ? "
        "AND stable_value = ? AND status = ?",
        (chat_id, entity_type, STABLE_KIND_TG_USER, stable_value,
         STATUS_ACTIVE),
    )


async def _ref_for_node(db, chat_id: int, entity_type: str, node: _NodeRow,
                        *, extra_alias: str | None = None) -> mc.EntityRef:
    """`EntityRef` канонического узла + свёрнутые member-узлы (§1.4)."""
    members = await _fetchall(
        db,
        f"SELECT c.member_node_id AS member_node_id, "
        "n.entity_name AS entity_name "
        f"FROM {ENTITY_CANONICAL_TABLE} c "
        "LEFT JOIN nodes n ON n.id = c.member_node_id "
        "WHERE c.chat_id = ? AND c.entity_type = ? "
        "AND c.canonical_node_id = ? AND c.status = ? "
        "ORDER BY c.member_node_id LIMIT ?",
        (chat_id, entity_type, node.node_id, STATUS_ACTIVE,
         _LEGACY_PREVIEW_MAX),
    )
    legacy: list[int] = []
    aliases: list[str] = []
    for row in members:
        member_id = int(_value(row, "member_node_id", 0))
        if member_id == node.node_id:
            continue
        legacy.append(member_id)
        name = _value(row, "entity_name", 1)
        if name and str(name) != node.entity_name:
            aliases.append(str(name))
    if extra_alias and extra_alias != node.entity_name:
        aliases.append(extra_alias)
    return mc.EntityRef(
        chat_id=chat_id, node_id=node.node_id, entity_type=entity_type,
        display_name=node.entity_name,
        legacy_ids=tuple(legacy),
        aliases=tuple(dict.fromkeys(aliases)),
    )


def _plain_ref(chat_id: int, entity_type: str, node: _NodeRow) -> mc.EntityRef:
    """`EntityRef` без чтения таблицы идентичности (OFF-паритет §1.7).

    OFF-ветка обязана быть байт-в-байт прежним поведением и работать на БД,
    где `mca_entity_canonical` ещё не создана: свёрнутых member-узлов и
    alias-карты тут нет по определению (`legacy_ids`/`aliases` пусты).
    """
    return mc.EntityRef(
        chat_id=chat_id, node_id=node.node_id, entity_type=entity_type,
        display_name=node.entity_name, legacy_ids=(), aliases=())


async def _redirect_target(db, chat_id: int, entity_type: str,
                           node: _NodeRow) -> tuple[_NodeRow, str, tuple[str, ...]]:
    """Схлопывание member→canonical на чтении (глубина 1, §1.4.2).

    Возвращает `(узел, reason_code, degraded)`. Цепочка (легаси/ручная правка)
    схлопывается до последнего достижимого узла и помечается честной
    деградацией; цикл виден событием `redirect_cycle_detected`. Данные не
    «выпрямляются» автоматически.
    """
    rows = await _active_rows_for_member(db, chat_id, entity_type, node.node_id)
    if not rows:
        return node, "", ()
    target_id = int(_value(rows[0], "canonical_node_id", 3))
    if target_id == node.node_id:
        return node, "", ()

    visited = {node.node_id}
    current = node
    steps = 0
    while True:
        if target_id in visited:
            _emit("memory.identity_redirect_cycle", outcome="failure",
                  chat_id=chat_id, status=REASON_REDIRECT_CYCLE,
                  entity_ids=[target_id])
            return node, REASON_REDIRECT_CYCLE, ("redirect_chain_flattened",)
        visited.add(target_id)
        target = await _node_by_id(db, target_id)
        if target is None:
            return current, "", ()
        steps += 1
        current = target
        next_rows = await _active_rows_for_member(
            db, chat_id, entity_type, target_id)
        if not next_rows:
            break
        next_id = int(_value(next_rows[0], "canonical_node_id", 3))
        if next_id == target_id or steps >= _REDIRECT_MAX_STEPS:
            break
        target_id = next_id

    if steps <= 1:
        return current, "", ()
    _emit("memory.identity_redirect_flattened", outcome="degraded",
          chat_id=chat_id, status=REASON_REDIRECT_FLATTENED,
          entity_ids=[current.node_id])
    return current, REASON_REDIRECT_FLATTENED, ("redirect_chain_flattened",)


async def _claimed_stable_values(db, chat_id: int, entity_type: str,
                                 node_id: int) -> list[str]:
    """Активные `tg_user`-значения, закреплённые за узлом (member **или**
    canonical): инвариант «ни один узел не обслуживает двух tg_user» (ID-11)."""
    rows = await _fetchall(
        db,
        f"SELECT stable_value FROM {ENTITY_CANONICAL_TABLE} "
        "WHERE chat_id = ? AND entity_type = ? AND stable_kind = ? "
        "AND status = ? AND (member_node_id = ? OR canonical_node_id = ?)",
        (chat_id, entity_type, STABLE_KIND_TG_USER, STATUS_ACTIVE, node_id,
         node_id),
    )
    values: list[str] = []
    for row in rows:
        value = _value(row, "stable_value", 0)
        if value is None:
            continue
        values.append(str(value))
    return values


def _stable_uid(stable_identity: Mapping[str, Any] | None) -> str | None:
    """`stable_identity` → `str(uid)`; иной kind не выдаётся за идентичность."""
    if not isinstance(stable_identity, Mapping):
        return None
    if str(stable_identity.get("kind") or "") != STABLE_KIND_TG_USER:
        return None
    value = stable_identity.get("value")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return str(value)


def parse_stable_identity(stable_identity: Any) -> str | None:
    """Публичная точка разбора `stable_identity` (`str(uid)` или `None`).

    Нужна слияниям B2 (`entity_merge`): доказательство и запись обязаны
    разбирать идентичность ОДНИМ кодом, а не второй копией правила.
    """
    return _stable_uid(stable_identity)


async def _identity_nodes_for_uid(db, chat_id: int, uid: str,
                                  *, aliases=None) -> list[_NodeRow]:
    """Узлы, соответствующие uid по §1.2.1 (без casefold и похожести).

    Кандидаты: `entity_name` **точно** равен одному из `resolve(uid)`,
    `canon_name(resolve(uid))` или любому `author_name`, наблюдавшемуся у uid.
    """
    names: set[str] = set()
    if aliases is None:
        try:
            from services.summary_aliases import build_alias_resolver
            aliases = await build_alias_resolver(chat_id)
        except Exception:
            logger.warning(
                "[entity_resolver] alias resolver unavailable | chat=%s",
                chat_id, exc_info=True)
            aliases = None
    if aliases is not None:
        try:
            resolved = str(aliases.resolve(int(uid)) or "").strip()
        except Exception:      # pragma: no cover — защитная ветка
            resolved = ""
        if resolved:
            names.add(resolved)
            try:
                canonical = str(aliases.canon_name(resolved) or "").strip()
            except Exception:  # pragma: no cover — защитная ветка
                canonical = ""
            if canonical:
                names.add(canonical)
    try:
        rows = await _fetchall(
            db,
            "SELECT DISTINCT author_name FROM smart_messages "
            "WHERE chat_id = ? AND user_id = ? AND author_name IS NOT NULL "
            "AND author_name <> ''",
            (chat_id, int(uid)),
        )
        for row in rows:
            text = str(_value(row, "author_name", 0) or "").strip()
            if text:
                names.add(text)
    except Exception:          # pragma: no cover — старые БД без колонки
        logger.debug("[entity_resolver] author names unavailable | chat=%s",
                     chat_id, exc_info=True)
    if not names:
        return []
    placeholders = ", ".join("?" for _ in names)
    rows = await _fetchall(
        db,
        "SELECT id, entity_name, entity_type FROM nodes "
        "WHERE chat_id = ? AND entity_type = 'user' "
        f"AND entity_name IN ({placeholders}) ORDER BY id",
        (chat_id, *sorted(names)),
    )
    return [_NodeRow(int(_value(row, "id", 0)),
                     str(_value(row, "entity_name", 1)),
                     str(_value(row, "entity_type", 2))) for row in rows]


async def _alias_nodes_for_mention(db, chat_id: int,
                                   mention: str) -> list[_NodeRow]:
    """Узлы, чей uid-алиас точно совпадает с mention (правило 2).

    Каскад имён — существующий `summary_aliases` (chat → global); второго
    словаря нет. Возвращаются узлы `Canon(uid)` (ровно написание каскада).
    """
    try:
        from services.summary_aliases import build_alias_resolver
        resolver = await build_alias_resolver(chat_id)
    except Exception:
        logger.warning("[entity_resolver] alias resolver unavailable | chat=%s",
                       chat_id, exc_info=True)
        return []
    uids = [uid for uid, name in (resolver.aliases or {}).items()
            if str(name or "").strip().lstrip("@").strip() == mention]
    if not uids:
        return []
    nodes: list[_NodeRow] = []
    seen: set[int] = set()
    for uid in uids:
        for node in await _identity_nodes_for_uid(db, chat_id, uid,
                                                  aliases=resolver):
            if node.node_id in seen:
                continue
            seen.add(node.node_id)
            nodes.append(node)
    return nodes


# ── конструкторы результатов ───────────────────────────────────────────────

def _raw_scope(chat_id: int, entity_type: str) -> mc.EntityScope:
    """`EntityScope` без валидации типа — только для честного `rejected` (§1.2 п.7).

    Типизированная модель MEMORY-01 не меняется: её конструктор по-прежнему
    отвергает недопустимый тип (внутренние инварианты целы), а фасад чтения
    обязан ответить `rejected`, а не бросать исключение (и уж точно не
    выбирать чужой тип). Такой экземпляр используется только в отчёте.
    """
    scope = object.__new__(mc.EntityScope)
    object.__setattr__(scope, "chat_id", chat_id)
    object.__setattr__(scope, "entity_type", entity_type)
    return scope


def _coerce_scope(scope: Any) -> tuple[mc.EntityScope, bool]:
    """`(scope, type_is_unsupported)`; тип вне четырёх — `rejected`, не raise."""
    if isinstance(scope, mc.EntityScope):
        return scope, False
    if not isinstance(scope, Mapping):
        raise ValueError("scope must be EntityScope or mapping with chat_id/"
                         "entity_type")
    entity_type = scope.get("entity_type")
    if entity_type not in mc.ENTITY_TYPES_ALLOWED:
        chat_id = scope.get("chat_id")
        if isinstance(chat_id, bool) or not isinstance(chat_id, int):
            chat_id = 0
        return _raw_scope(chat_id, str(entity_type)), True
    return mc.EntityScope(chat_id=scope["chat_id"],
                          entity_type=entity_type), False


def _mention_text(mention: Any) -> str:
    if not isinstance(mention, str):
        return ""
    return _nfc(mention).strip()[:mc.ENTITY_MENTION_MAX_CHARS]


def _rejected(scope: mc.EntityScope, mention: Any, reason: str,
              *, candidates: tuple[mc.ResolutionCandidate, ...] = (),
              degraded: tuple[str, ...] = ()) -> mc.EntityResolution:
    return mc.EntityResolution(
        status=mc.EntityResolutionStatus.REJECTED, scope=scope,
        normalized_mention=_mention_text(mention), candidates=candidates,
        reason_code=reason, degraded=degraded)


def _resolved(scope: mc.EntityScope, ref: mc.EntityRef, reason: str,
              *, mention: Any, degraded: tuple[str, ...] = ()
              ) -> mc.EntityResolution:
    return mc.EntityResolution(
        status=mc.EntityResolutionStatus.RESOLVED, scope=scope,
        normalized_mention=_mention_text(mention), canonical=ref,
        reason_code=reason, degraded=degraded)


def _new(scope: mc.EntityScope, mention: Any, reason: str,
         degraded: tuple[str, ...] = ()) -> mc.EntityResolution:
    return mc.EntityResolution(
        status=mc.EntityResolutionStatus.NEW, scope=scope,
        normalized_mention=_mention_text(mention), reason_code=reason,
        degraded=degraded)


def _ambiguous(scope: mc.EntityScope, mention: Any, reason: str,
               candidates: list[mc.ResolutionCandidate],
               degraded: tuple[str, ...] = ()) -> mc.EntityResolution:
    return mc.EntityResolution(
        status=mc.EntityResolutionStatus.AMBIGUOUS, scope=scope,
        normalized_mention=_mention_text(mention),
        candidates=tuple(candidates), reason_code=reason, degraded=degraded)


# ── разрешение идентичности ────────────────────────────────────────────────

async def _conflict_resolution(
        db, scope: mc.EntityScope, mention: Any, node: _NodeRow,
        uid: str, others: list[str], *, aliases=None) -> mc.EntityResolution:
    """`ambiguous` при подмене личности: узел уже закреплён за другим uid.

    Оба uid попадают в `candidates`; автовыбор и перезапись `stable_value`
    запрещены (§1.2.1, ID-11).
    """
    ref = await _ref_for_node(db, scope.chat_id, scope.entity_type, node)
    own_nodes = await _identity_nodes_for_uid(db, scope.chat_id, uid,
                                              aliases=aliases)
    own = next((n for n in own_nodes if n.node_id != node.node_id), None)
    own_ref = (await _ref_for_node(db, scope.chat_id, scope.entity_type, own)
               if own is not None else ref)
    _emit("memory.identity_node_conflict", outcome="conflict",
          chat_id=scope.chat_id, status=REASON_IDENTITY_NODE_CONFLICT,
          entity_ids=[node.node_id])
    return _ambiguous(
        scope, mention, REASON_IDENTITY_NODE_CONFLICT,
        [mc.ResolutionCandidate(ref=ref, reason="identity_claimed",
                                discriminator=f"uid: {others[0]}"),
         mc.ResolutionCandidate(ref=own_ref, reason="identity_requested",
                                discriminator=f"uid: {uid}")])


async def _finish_node(scope: mc.EntityScope, db, node: _NodeRow, *,
                       mention: Any, reason: str,
                       degraded: tuple[str, ...] = ()) -> mc.EntityResolution:
    """Разрешённый узел + redirect глубины 1 (§1.4.2)."""
    if node.entity_type != scope.entity_type:
        return await _type_conflict(scope, db, node, mention)
    target, redirect_reason, redirect_degraded = await _redirect_target(
        db, scope.chat_id, scope.entity_type, node)
    if target.entity_type != scope.entity_type:
        return await _type_conflict(scope, db, target, mention)
    ref = await _ref_for_node(db, scope.chat_id, scope.entity_type, target)
    return _resolved(scope, ref, redirect_reason or reason, mention=mention,
                     degraded=tuple(dict.fromkeys(
                         tuple(degraded) + redirect_degraded)))


async def _type_conflict(scope: mc.EntityScope, db, node: _NodeRow,
                         mention: Any) -> mc.EntityResolution:
    """Один слот имени на чат (§1.2.3): тип чужой — `rejected`, не `resolved`.

    Ref собирается без чтения `mca_entity_canonical`: конфликт типа обязан
    работать и в OFF-режиме, и на БД до миграции `v43` (F4).
    """
    ref = _plain_ref(scope.chat_id, node.entity_type, node)
    _emit("memory.entity_type_conflict", outcome="conflict",
          chat_id=scope.chat_id, status=REASON_TYPE_CONFLICT,
          entity_ids=[node.node_id])
    return _rejected(
        scope, mention, REASON_TYPE_CONFLICT,
        candidates=(mc.ResolutionCandidate(
            ref=ref, reason=REASON_TYPE_CONFLICT,
            discriminator=f"другой тип: {node.entity_type}"),))


async def resolve_entity(
        db=None, *, scope: Any, mention: str,
        stable_identity: Mapping[str, Any] | None = None,
        evidence: Mapping[str, Any] | None = None,
        allow_create: bool = False) -> mc.EntityResolution:
    """Разрешение идентичности по §1.2 (первое решающее правило выигрывает).

    Порядок: `tg_user` → подтверждённый alias → точное имя в типе → ограниченный
    casefold-скан → redirect глубины 1 → `new`. `rejected` — неподдерживаемый
    `entity_type` (§1.2 п.7, никогда не `new` и никогда не чужой тип), пустой/
    пробельный или слишком длинный mention, а также конфликт типа на точном
    имени (`type_conflict_single_slot`, §1.2.3). `ambiguous` — реальная
    неоднозначность (два uid на один узел, несколько кандидатов, переполнение
    префикса): автовыбор запрещён (ID-8).

    **Ничего не пишет** (ID-1). `allow_create` не создаёт узел: создание —
    только `resolve_or_create_node` (§1.4.1); аргумент сохранён ради формы
    контракта §1.1 и на запись не влияет. `evidence` принимается по той же
    причине: в C-1 идентичность доказывается только uid/alias-картой/точным
    именем, а evidence-строки появляются у слияний `B2` (§5.3), не здесь.

    `db` — `DatabaseService`; обязателен (в подписи §1.1 его нет, но резолвер
    не держит собственного соединения/кэша идентичности). Кэша нет, поэтому
    композитная ревизия §2.4.3 не нужна: ответ детерминирован по входу и БД.
    """
    if db is None:
        raise RuntimeError("resolve_entity requires a DatabaseService (db)")
    entity_scope, unsupported_type = _coerce_scope(scope)
    chat_id = entity_scope.chat_id
    entity_type = entity_scope.entity_type
    if unsupported_type:
        # §1.2 п.7: неподдерживаемый тип — `rejected`, не `new` и не `resolved`.
        return _rejected(entity_scope, mention, REASON_INVALID_ENTITY_TYPE)

    text = _mention_text(mention)
    if not isinstance(mention, str) or not text:
        return _rejected(entity_scope, mention, REASON_EMPTY_MENTION)
    if len(_nfc(mention).strip()) > mc.ENTITY_MENTION_MAX_CHARS:
        return _rejected(entity_scope, mention, REASON_MENTION_TOO_LONG)

    if not await memory_identity_enabled(chat_id):
        # OFF-паритет §1.7: сегодняшний точный путь. Таблица идентичности не
        # читается ВООБЩЕ (её может не быть до миграции `v43`): ref строится
        # без свёрнутых member-узлов/alias-карты, как прежний `upsert_node`.
        legacy = await _node_by_exact_name(db, chat_id, mention)
        if legacy is None:
            return _new(entity_scope, mention, REASON_NO_MATCH)
        if legacy.entity_type != entity_type:
            return await _type_conflict(entity_scope, db, legacy, mention)
        ref = _plain_ref(chat_id, entity_type, legacy)
        return _resolved(entity_scope, ref, REASON_EXACT_NAME, mention=mention)

    degraded: list[str] = []
    uid = _stable_uid(stable_identity)

    # ── правило 1: устойчивая идентичность Telegram ────────────────────────
    if uid is not None:
        claims = await _active_self_rows(db, chat_id, entity_type, uid)
        if len(claims) == 1:
            canonical_id = int(_value(claims[0], "canonical_node_id", 3))
            node = await _node_by_id(db, canonical_id)
            if node is not None:
                return await _finish_node(
                    entity_scope, db, node, mention=mention,
                    reason=REASON_STABLE_IDENTITY)
            degraded.append(REASON_IDENTITY_NOT_SEEDED)
        elif len(claims) > 1:
            candidates: list[mc.ResolutionCandidate] = []
            for claim in claims[:_AMBIGUOUS_PREVIEW_MAX]:
                canonical_id = int(_value(claim, "canonical_node_id", 3))
                node = await _node_by_id(db, canonical_id)
                if node is None:
                    continue
                ref = await _ref_for_node(db, chat_id, entity_type, node)
                candidates.append(mc.ResolutionCandidate(
                    ref=ref, reason=REASON_IDENTITY_DUPLICATE_CLAIM,
                    discriminator=f"uid: {uid}"))
            if len(candidates) >= 2:
                return _ambiguous(entity_scope, mention,
                                  REASON_IDENTITY_DUPLICATE_CLAIM, candidates)
            degraded.append(REASON_IDENTITY_NOT_SEEDED)
        else:
            # Строки нет: правило 1 считается НЕ сработавшим (не «по имени»).
            degraded.append(REASON_IDENTITY_NOT_SEEDED)

    # ── правило 2: подтверждённый alias-каскад (только люди, ID-5) ─────────
    if entity_type == "user":
        alias_nodes = await _alias_nodes_for_mention(db, chat_id, text)
        if len(alias_nodes) == 1:
            node = alias_nodes[0]
            if uid is not None:
                others = [v for v in await _claimed_stable_values(
                    db, chat_id, entity_type, node.node_id) if v != uid]
                if others:
                    return await _conflict_resolution(
                        db, entity_scope, mention, node, uid, others)
            return await _finish_node(entity_scope, db, node, mention=mention,
                                      reason=REASON_ALIAS_MAP,
                                      degraded=tuple(degraded))
        if len(alias_nodes) > 1:
            candidates = []
            for node in alias_nodes[:_AMBIGUOUS_PREVIEW_MAX]:
                ref = await _ref_for_node(db, chat_id, entity_type, node)
                candidates.append(mc.ResolutionCandidate(
                    ref=ref, reason=REASON_ALIAS_MAP,
                    discriminator=f"узел: {node.node_id}"))
            return _ambiguous(entity_scope, mention, REASON_ALIAS_MAP,
                              candidates, tuple(degraded))

    # ── правило 3: точное имя в пределах запрошенного типа ─────────────────
    exact = await _node_by_exact_name(db, chat_id, mention)
    if exact is not None:
        if exact.entity_type != entity_type:
            return await _type_conflict(entity_scope, db, exact, mention)
        if uid is not None:
            others = [v for v in await _claimed_stable_values(
                db, chat_id, entity_type, exact.node_id) if v != uid]
            if others:
                return await _conflict_resolution(
                    db, entity_scope, mention, exact, uid, others)
        return await _finish_node(entity_scope, db, exact, mention=mention,
                                  reason=REASON_EXACT_NAME,
                                  degraded=tuple(degraded))

    # ── правило 4: ограниченная генерация casefold-кандидатов ──────────────
    matches, overflow_rows = await _casefold_scan(
        db, chat_id, entity_type, text)
    if overflow_rows:
        _emit("memory.identity_casefold_overflow", outcome="degraded",
              chat_id=chat_id, status=REASON_CASEFOLD_OVERFLOW,
              entity_ids=[n.node_id for n in overflow_rows])
        candidates = []
        for node in overflow_rows[:_AMBIGUOUS_PREVIEW_MAX]:
            ref = await _ref_for_node(db, chat_id, entity_type, node)
            candidates.append(mc.ResolutionCandidate(
                ref=ref, reason=REASON_CASEFOLD_OVERFLOW,
                discriminator=f"написание: {node.entity_name}"))
        return _ambiguous(entity_scope, mention, REASON_CASEFOLD_OVERFLOW,
                          candidates, ("casefold_prefix_overflow",))
    if len(matches) == 1:
        node = matches[0]
        if uid is not None:
            others = [v for v in await _claimed_stable_values(
                db, chat_id, entity_type, node.node_id) if v != uid]
            if others:
                return await _conflict_resolution(
                    db, entity_scope, mention, node, uid, others)
        return await _finish_node(entity_scope, db, node, mention=mention,
                                  reason=REASON_CASEFOLD_UNIQUE,
                                  degraded=tuple(degraded))
    if len(matches) > 1:
        candidates = []
        for node in matches[:_AMBIGUOUS_PREVIEW_MAX]:
            ref = await _ref_for_node(db, chat_id, entity_type, node)
            candidates.append(mc.ResolutionCandidate(
                ref=ref, reason=REASON_CASEFOLD_MULTIPLE,
                discriminator=f"написание: {node.entity_name}"))
        return _ambiguous(entity_scope, mention, REASON_CASEFOLD_MULTIPLE,
                          candidates, tuple(degraded))

    # ── правило 6: ничего не найдено (создание — только §1.4.1) ────────────
    return _new(entity_scope, mention, REASON_NO_MATCH, tuple(degraded))


# ── засев self-строк (B2-0, §1.2.1/§5.3) ───────────────────────────────────

@dataclasses.dataclass(frozen=True)
class SeedResult:
    """Детерминированный исход засева `B2-0` (идемпотентно по PK)."""

    status: str
    chat_id: int
    user_id: int
    node_id: int | None = None
    candidate_node_ids: tuple[int, ...] = ()
    reason_code: str = ""
    degraded: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "status": self.status, "chat_id": self.chat_id,
            "user_id": self.user_id, "node_id": self.node_id,
            "candidate_node_ids": list(self.candidate_node_ids),
            "reason_code": self.reason_code,
            "degraded": list(self.degraded),
        }


async def seed_self_identity(db, chat_id: int, user_id: int, *,
                             aliases=None, now: int | None = None
                             ) -> SeedResult:
    """Засев self-строки `tg_user` по §1.2.1 (`B2-0`).

    Исходы: `seeded` | `identity_seed_already_pinned` |
    `identity_seed_missing` (0 кандидатов, `degraded=['identity_not_seeded']`) |
    `identity_seed_ambiguous` (>1) | `identity_seed_node_conflict` (узел уже
    закреплён за другим uid) | `identity_seed_skipped_revoked`. Ни одного
    `INSERT OR REPLACE`: `stable_value` существующей строки не перезаписывается.
    """
    uid = str(int(user_id))
    stamp = int(now if now is not None else time.time())

    claims = await _active_self_rows(db, int(chat_id), "user", uid)
    if claims:
        return SeedResult(
            status=SEED_ALREADY_PINNED, chat_id=int(chat_id),
            user_id=int(user_id),
            node_id=int(_value(claims[0], "member_node_id", 2)),
            reason_code=SEED_ALREADY_PINNED)

    candidates = await _identity_nodes_for_uid(db, int(chat_id), uid,
                                              aliases=aliases)
    candidate_ids = tuple(node.node_id for node in candidates)
    if not candidates:
        _emit("memory.identity_seed_missing", outcome="degraded",
              chat_id=int(chat_id), status=SEED_MISSING)
        return SeedResult(status=SEED_MISSING, chat_id=int(chat_id),
                          user_id=int(user_id), reason_code=SEED_MISSING,
                          degraded=("identity_not_seeded",))
    if len(candidates) > 1:
        _emit("memory.identity_seed_ambiguous", outcome="conflict",
              chat_id=int(chat_id), status=SEED_AMBIGUOUS,
              entity_ids=list(candidate_ids[:_AMBIGUOUS_PREVIEW_MAX]))
        return SeedResult(status=SEED_AMBIGUOUS, chat_id=int(chat_id),
                          user_id=int(user_id),
                          candidate_node_ids=candidate_ids,
                          reason_code=SEED_AMBIGUOUS)

    node = candidates[0]
    claimed = await _claimed_stable_values(db, int(chat_id), "user",
                                           node.node_id)
    if any(value != uid for value in claimed):
        _emit("memory.identity_seed_node_conflict", outcome="conflict",
              chat_id=int(chat_id), status=SEED_NODE_CONFLICT,
              entity_ids=[node.node_id])
        return SeedResult(status=SEED_NODE_CONFLICT, chat_id=int(chat_id),
                          user_id=int(user_id), node_id=node.node_id,
                          candidate_node_ids=candidate_ids,
                          reason_code=SEED_NODE_CONFLICT)

    existing = await _fetchone(
        db,
        f"SELECT status FROM {ENTITY_CANONICAL_TABLE} "
        "WHERE chat_id = ? AND entity_type = ? AND member_node_id = ?",
        (int(chat_id), "user", node.node_id),
    )
    if existing is not None:
        # Строка уже есть (в т.ч. отозванная): автоматически не оживляем —
        # ремонт только явным админским шагом (§1.4.2).
        status = str(_value(existing, "status", 0))
        reason = (SEED_ALREADY_PINNED if status == STATUS_ACTIVE
                  else SEED_REVOKED)
        return SeedResult(status=reason, chat_id=int(chat_id),
                          user_id=int(user_id), node_id=node.node_id,
                          candidate_node_ids=candidate_ids, reason_code=reason)

    async def _insert(conn):
        await conn.execute(
            f"INSERT INTO {ENTITY_CANONICAL_TABLE} ("
            "chat_id, entity_type, member_node_id, canonical_node_id, "
            "resolution, stable_kind, stable_value, method, evidence_ref_id, "
            "confidence, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (int(chat_id), "user", node.node_id, node.node_id,
             RESOLUTION_SELF, STABLE_KIND_TG_USER, uid, METHOD_ALIAS_MAP, None,
             CONFIDENCE_CONFIRMED, STATUS_ACTIVE, stamp, stamp),
        )

    try:
        await db.write_transaction(_insert, op_name="entity_seed_self",
                                   chat_id=int(chat_id))
    except sqlite3.IntegrityError:
        # PK/частичный UNIQUE: параллельный/повторный засев — не перезапись.
        again = await _active_self_rows(db, int(chat_id), "user", uid)
        if again:
            return SeedResult(status=SEED_ALREADY_PINNED, chat_id=int(chat_id),
                              user_id=int(user_id),
                              node_id=int(_value(again[0],
                                                 "member_node_id", 2)),
                              reason_code=SEED_ALREADY_PINNED)
        _emit("memory.identity_seed_node_conflict", outcome="conflict",
              chat_id=int(chat_id), status=SEED_NODE_CONFLICT,
              entity_ids=[node.node_id])
        return SeedResult(status=SEED_NODE_CONFLICT, chat_id=int(chat_id),
                          user_id=int(user_id), node_id=node.node_id,
                          candidate_node_ids=candidate_ids,
                          reason_code=SEED_NODE_CONFLICT)

    _emit("memory.identity_seed", outcome="success", chat_id=int(chat_id),
          status=SEED_SEEDED, entity_ids=[node.node_id])
    return SeedResult(status=SEED_SEEDED, chat_id=int(chat_id),
                      user_id=int(user_id), node_id=node.node_id,
                      candidate_node_ids=candidate_ids,
                      reason_code=SEED_SEEDED)


# ── единственная точка создания узла (§1.4.1) ──────────────────────────────

@dataclasses.dataclass(frozen=True)
class ResolvedNode:
    """Результат `resolve_or_create_node` для писателей W1–W6.

    `node_id` — id для записи ребра/факта (канонический, если найден redirect);
    `created` — узел создан этим вызовом; `status='rejected'` с
    `reason_code='type_conflict_single_slot'` — конфликт типа: ребро не
    пишется, факт сохраняется без связи (§1.2.3).
    """

    node_id: int | None
    canonical_id: int | None
    created: bool
    status: str
    reason_code: str
    resolution: mc.EntityResolution

    def as_dict(self) -> dict:
        return {
            "node_id": self.node_id, "canonical_id": self.canonical_id,
            "created": self.created, "status": self.status,
            "reason_code": self.reason_code,
            "resolution": self.resolution.as_dict(),
        }


async def resolve_or_create_node(
        db, chat_id: int, name: str, entity_type: str, *,
        stable_identity: Mapping[str, Any] | None = None,
        evidence: Mapping[str, Any] | None = None,
        allow_create: bool = True, origin: str = "chat_history",
        expires_at=None, commit: bool = True) -> ResolvedNode:
    """Единственная точка создания узла (§1.4.1): резолв → создание.

    При `new` и `allow_create` создание идёт существующим `upsert_node`
    **внутри транзакции писателя**; при конфликте типа создание отменяется
    (иначе `INSERT OR IGNORE` молча оставил бы чужой тип), событие
    `entity_type_conflict`. OFF-гейт → байт-в-байт сегодняшний путь
    (`upsert_node` без новых чтений): тип возвращённого узла — тот, что
    занимает слот имени в чате.

    `commit=False` — транзакцией владеет вызывающий (он уже держит
    `db.serialized()`/`write_transaction`, §1.4.1 «внутри транзакции
    писателя»): так W2 (`_write_graph_triplets`) пишет узлы и рёбра одной
    транзакцией, как до слайса. Дефолт `True` — поведение W1 и прочих
    вызовов не меняется.
    """
    chat_id = int(chat_id)
    entity_type = str(entity_type)

    if not await memory_identity_enabled(chat_id):
        before = await _node_by_exact_name(db, chat_id, name)
        node_id = await db.upsert_node(chat_id, name, entity_type,
                                       origin=origin, expires_at=expires_at,
                                       commit=commit)
        stored = await _node_by_id(db, int(node_id))
        actual_type = stored.entity_type if stored is not None else entity_type
        legacy_scope = _coerce_scope({"chat_id": chat_id,
                                      "entity_type": actual_type})[0]
        if stored is not None:
            ref = _plain_ref(chat_id, actual_type, stored)
            resolution = _resolved(legacy_scope, ref, REASON_EXACT_NAME,
                                   mention=name)
        else:
            resolution = _new(legacy_scope, name, REASON_CREATED)
        return ResolvedNode(
            node_id=int(node_id), canonical_id=int(node_id),
            created=before is None, status="resolved",
            reason_code=(REASON_EXACT_NAME if before is not None
                         else REASON_CREATED),
            resolution=resolution)

    scope, unsupported_type = _coerce_scope(
        {"chat_id": chat_id, "entity_type": entity_type})
    if unsupported_type:
        rejected = _rejected(scope, name, REASON_INVALID_ENTITY_TYPE)
        return ResolvedNode(
            node_id=None, canonical_id=None, created=False,
            status=rejected.status.value,
            reason_code=REASON_INVALID_ENTITY_TYPE, resolution=rejected)
    resolution = await resolve_entity(
        db, scope=scope, mention=name, stable_identity=stable_identity,
        evidence=evidence, allow_create=allow_create)

    if resolution.status is mc.EntityResolutionStatus.RESOLVED:
        canonical = resolution.canonical
        return ResolvedNode(
            node_id=canonical.node_id, canonical_id=canonical.node_id,
            created=False, status=resolution.status.value,
            reason_code=resolution.reason_code or REASON_EXACT_NAME,
            resolution=resolution)

    if resolution.status is not mc.EntityResolutionStatus.NEW:
        return ResolvedNode(
            node_id=None, canonical_id=None, created=False,
            status=resolution.status.value,
            reason_code=resolution.reason_code, resolution=resolution)

    if not allow_create:
        return ResolvedNode(
            node_id=None, canonical_id=None, created=False,
            status=resolution.status.value,
            reason_code=resolution.reason_code or REASON_NO_MATCH,
            resolution=resolution)

    # Гонка/тип: слот имени один на чат (UNIQUE(chat_id, entity_name)).
    occupant = await _node_by_exact_name(db, chat_id, name)
    if occupant is not None:
        if occupant.entity_type != entity_type:
            rejected = await _type_conflict(scope, db, occupant, name)
            return ResolvedNode(
                node_id=None, canonical_id=None, created=False,
                status=rejected.status.value,
                reason_code=REASON_TYPE_CONFLICT, resolution=rejected)
        return ResolvedNode(
            node_id=occupant.node_id, canonical_id=occupant.node_id,
            created=False, status=mc.EntityResolutionStatus.RESOLVED.value,
            reason_code=REASON_EXACT_NAME, resolution=resolution)

    node_id = await db.upsert_node(chat_id, name, entity_type,
                                   origin=origin, expires_at=expires_at,
                                   commit=commit)
    stored = await _node_by_id(db, int(node_id))
    if stored is not None and stored.entity_type != entity_type:
        # `INSERT OR IGNORE` вернул чужой узел — не выдаём это за создание.
        rejected = await _type_conflict(scope, db, stored, name)
        return ResolvedNode(
            node_id=None, canonical_id=None, created=False,
            status=mc.EntityResolutionStatus.REJECTED.value,
            reason_code=REASON_TYPE_CONFLICT, resolution=rejected)
    return ResolvedNode(
        node_id=int(node_id), canonical_id=int(node_id), created=True,
        status=mc.EntityResolutionStatus.NEW.value,
        reason_code=REASON_CREATED, resolution=resolution)


__all__ = [
    "ENTITY_CANONICAL_TABLE",
    "ENTITY_CANONICAL_MIGRATION_STEP_NAME",
    "ENTITY_CANONICAL_DDL_SQLITE",
    "ENTITY_CANONICAL_INDEX_DDL",
    "ENTITY_CASEFOLD_SCAN_LIMIT",
    "CASEFOLD_SCAN_SQL",    "RESOLUTION_SELF", "RESOLUTION_ALIAS", "RESOLUTION_MERGED",
    "STATUS_ACTIVE", "STATUS_REVOKED", "STABLE_KIND_TG_USER",
    "METHOD_ALIAS_MAP", "METHOD_EXPLICIT_EVIDENCE", "METHOD_MANUAL_ADMIN",
    "CONFIDENCE_CONFIRMED", "CONFIDENCE_TENTATIVE",
    "REASON_STABLE_IDENTITY", "REASON_ALIAS_MAP", "REASON_EXACT_NAME",
    "REASON_CASEFOLD_UNIQUE", "REASON_CASEFOLD_MULTIPLE",
    "REASON_CASEFOLD_OVERFLOW", "REASON_TYPE_CONFLICT",
    "REASON_IDENTITY_NODE_CONFLICT", "REASON_IDENTITY_NOT_SEEDED",
    "REASON_REDIRECT_FLATTENED", "REASON_EMPTY_MENTION",
    "REASON_MENTION_TOO_LONG", "REASON_INVALID_ENTITY_TYPE", "REASON_NO_MATCH",
    "SEED_SEEDED", "SEED_ALREADY_PINNED", "SEED_MISSING", "SEED_AMBIGUOUS",
    "SEED_NODE_CONFLICT", "SEED_REVOKED",
    "SeedResult", "seed_self_identity",
    "ResolvedNode", "resolve_or_create_node", "resolve_entity",
    "parse_stable_identity",
]
