"""EVOL-016 — релизная политика промптов: журнал ревизий и активаций.

Нормативная база:
  * ``plans/features/evol/arch/contracts.md`` CONTRACT 1 (заморожен) —
    автомат активации, схема журнала, снимок legacy, scope-правила;
  * решение владельца 29.10.2026 (EVOL-012): новая заводская ревизия в
    составе релиза активируется автоматически ДАЖЕ поверх ручной правки;
    рестарт без новой метки ничего не меняет; ручные правки становятся
    неизменяемой историей; строковые сравнения с канонами запрещены;
  * ``plans/current_task.md`` §5 (EVOL-016/017/018) — семантика приоритетов
    1–5, граница «нового заводского релиза», надёжность.

Что здесь живёт:
  * журнал ``prompt_revisions`` / ``prompt_activations`` (PostgreSQL, те же
    контуры долговечности, что и ``bot_settings``) + in-memory стор для
    тестов (та же семантика, откат пакета и инъекция сбоев);
  * ``apply_release`` — детерминированное применение заводского релиза
    (cutover/деплой/рестарт) одной PG-транзакцией под advisory-локом;
  * снимок legacy перед первой записью заводского текста (``origin=legacy``,
    время = время импорта, автор не выдумывается);
  * ``write_versioned_value`` — единственная версионированная запись
    активного текста (ревизия + активация + значение в одной транзакции);
  * ``activate_revision`` / ``list_versions`` / ``get_revision_source`` /
    ``diff_revisions`` — сервисный API для EVOL-017 (админка), без HTTP.

Схема: DDL журнала самодостаточен и идемпотентен (``ensure_journal``);
интеграция книги схемы выполнена (заметка w2a-evol016.md §4): SQLite
user_version 39 (``prompt_revision_journal_v39``), тот же DDL дословно
перенесён в ``pg_db.DDL_STATEMENTS`` — таблицы создаются при инициализации
пула, ленивый ``ensure_journal`` остаётся совместимым путём (те же
выражения, повтор — no-op). Журнал НЕ дублирует активный текст как второй
источник правды: пайплайны читают активные байты по-прежнему из
``bot_settings`` / chat-override; последняя строка ``prompt_activations``
(``outcome ∈ {applied, skipped_same}``) — указатель «какая ревизия включена»
и «какая заводская ревизия уже применена».

TEST-LIFECYCLE: CONTRACT owner=EVOL-016 (tests/test_evol016_prompt_activation.py)
"""
from __future__ import annotations

import asyncio
import datetime
import difflib
import json
import logging
from dataclasses import dataclass
from typing import Callable, Iterable

from services import prompt_registry as pr

logger = logging.getLogger(__name__)

#: Идентификатор одноразового миграционного релиза (первое включение
#: механизма: снимок legacy → активация текущей заводской ревизии).
CUTOVER_RELEASE_ID = "evol-016-cutover"

#: Advisory-лок применения релиза (прецедент chat_params.ADVISORY_LOCK_SQL).
APPLY_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext('prompt_release_apply'))"

#: DDL журнала (контракт §1.2, дословные имена таблиц/полей). Идемпотентен.
JOURNAL_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS prompt_revisions (
        revision_id        TEXT PRIMARY KEY,
        block_id           TEXT NOT NULL,
        pg_key             TEXT NOT NULL DEFAULT '',
        scope              TEXT NOT NULL,
        chat_id            BIGINT,
        origin             TEXT NOT NULL,
        content_sha12      TEXT NOT NULL,
        body               TEXT NOT NULL,
        factory_revision   TEXT NOT NULL DEFAULT '',
        schema_compat      TEXT NOT NULL DEFAULT '',
        release_id         TEXT NOT NULL DEFAULT '',
        actor              TEXT NOT NULL DEFAULT '',
        reason             TEXT NOT NULL DEFAULT '',
        source_updated_at  TEXT NOT NULL DEFAULT '',
        retired            BOOLEAN NOT NULL DEFAULT false,
        created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_prompt_revisions_block "
    "ON prompt_revisions (block_id, scope, created_at)",
    """
    CREATE TABLE IF NOT EXISTS prompt_activations (
        activation_id              BIGSERIAL PRIMARY KEY,
        block_id                   TEXT NOT NULL,
        scope                      TEXT NOT NULL,
        chat_id                    BIGINT,
        revision_id                TEXT NOT NULL DEFAULT '',
        factory_revision_applied   TEXT NOT NULL DEFAULT '',
        kind                       TEXT NOT NULL,
        outcome                    TEXT NOT NULL,
        release_id                 TEXT NOT NULL DEFAULT '',
        actor                      TEXT NOT NULL DEFAULT '',
        detail_code                TEXT NOT NULL DEFAULT '',
        created_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_prompt_activations_latest "
    "ON prompt_activations (block_id, scope, activation_id DESC)",
)

#: Совместимые значения schema_compat текущего runtime. В этой волне список
#: ПУСТ: «пусто в ревизии» = совместима со всем; непустая метка в ревизии =
#: не активируется (читать/сравнивать можно, включать нельзя — EVOL-017).
SUPPORTED_SCHEMA_COMPAT: frozenset[str] = frozenset()

_UPSERT_BOT_SETTING_SQL = """
INSERT INTO bot_settings (key, value, category)
VALUES ($1, $2::jsonb, $3)
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value, category = EXCLUDED.category,
    updated_at = now()
"""
_NOTIFY_CHAT_SQL = "SELECT pg_notify('chat_params_updated', $1)"
_DROP_CHAT_OVERRIDE_SQL = """
UPDATE chat_profiles
SET chat_params = jsonb_set(
        chat_params, '{overrides}',
        COALESCE(chat_params -> 'overrides', '{}'::jsonb) - $2, true),
    updated_at = now()
WHERE chat_id = $1 AND chat_params ? 'overrides'
  AND (chat_params -> 'overrides') ? $2
"""
_SET_CHAT_OVERRIDE_SQL = """
UPDATE chat_profiles
SET chat_params = jsonb_set(
        chat_params, '{overrides}',
        COALESCE(chat_params -> 'overrides', '{}'::jsonb) ||
        jsonb_build_object($2::text, $3::jsonb), true),
    updated_at = now()
WHERE chat_id = $1
"""
_SELECT_CHAT_OVERRIDES_SQL = """
SELECT chat_id, chat_params -> 'overrides' -> $1 AS value
FROM chat_profiles
WHERE chat_params ? 'overrides' AND (chat_params -> 'overrides') ? $1
  AND chat_params -> 'overrides' -> $1 IS NOT NULL
"""
_SELECT_BOT_SETTING_SQL = (
    "SELECT value #>> '{}' AS text FROM bot_settings WHERE key = $1")
_INSERT_REVISION_SQL = """
INSERT INTO prompt_revisions (revision_id, block_id, pg_key, scope, chat_id,
                              origin, content_sha12, body, factory_revision,
                              schema_compat, release_id, actor, reason,
                              source_updated_at, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
        COALESCE($15, now()))
ON CONFLICT (revision_id) DO NOTHING
"""
_INSERT_ACTIVATION_SQL = """
INSERT INTO prompt_activations (block_id, scope, chat_id, revision_id,
                                factory_revision_applied, kind, outcome,
                                release_id, actor, detail_code)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
RETURNING activation_id
"""
_LAST_APPLIED_SQL = """
SELECT activation_id, revision_id, factory_revision_applied, kind
FROM prompt_activations
WHERE block_id = $1 AND scope = $2 AND (chat_id = $3
                                        OR (chat_id IS NULL AND $3 IS NULL))
  AND outcome IN ('applied', 'skipped_same')
ORDER BY activation_id DESC LIMIT 1
"""
_HAS_IMPORT_SQL = """
SELECT 1 FROM prompt_revisions
WHERE block_id = $1 AND scope = $2 AND (chat_id = $3
                                        OR (chat_id IS NULL AND $3 IS NULL))
  AND origin = 'legacy' LIMIT 1
"""
_HAS_CUTOVER_SQL = """
SELECT 1 FROM prompt_activations
WHERE block_id = $1 AND scope = $2 AND (chat_id = $3
                                        OR (chat_id IS NULL AND $3 IS NULL))
  AND kind = 'legacy_import' LIMIT 1
"""
_GET_REVISION_SQL = (
    "SELECT revision_id, block_id, pg_key, scope, chat_id, origin, "
    "content_sha12, body, factory_revision, schema_compat, release_id, "
    "actor, reason, source_updated_at, retired, created_at "
    "FROM prompt_revisions WHERE revision_id = $1")
_LIST_REVISIONS_SQL = """
SELECT revision_id, block_id, pg_key, scope, chat_id, origin, content_sha12,
       factory_revision, schema_compat, release_id, actor, reason,
       source_updated_at, retired, created_at
FROM prompt_revisions
WHERE block_id = $1 AND (chat_id = $2 OR (chat_id IS NULL AND $2 IS NULL))
ORDER BY created_at ASC, revision_id ASC
"""
_LIST_ACTIVATIONS_SQL = """
SELECT activation_id, block_id, scope, chat_id, revision_id,
       factory_revision_applied, kind, outcome, release_id, actor,
       detail_code, created_at
FROM prompt_activations
WHERE block_id = $1 AND (chat_id = $2 OR (chat_id IS NULL AND $2 IS NULL))
ORDER BY activation_id DESC LIMIT $3
"""
_KNOWN_BLOCK_IDS_SQL = "SELECT DISTINCT block_id FROM prompt_revisions"
_MARK_RETIRED_SQL = (
    "UPDATE prompt_revisions SET retired = true "
    "WHERE block_id = ANY($1) AND retired = false")


# ═══════════════════════════════════════════════════════════════════════════
# Модель строк журнала
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class RevisionRow:
    """Неизменяемая ревизия текста (контракт §1.2)."""

    revision_id: str
    block_id: str
    scope: str                     # global | chat | code
    origin: str                    # factory | manual | restored | legacy
    content_sha12: str
    body: str
    pg_key: str = ""
    chat_id: int | None = None
    factory_revision: str = ""     # fac:<sha12(метки)> для origin=factory
    schema_compat: str = ""
    release_id: str = ""
    actor: str = ""
    reason: str = ""
    source_updated_at: str = ""
    retired: bool = False
    created_at: str = ""


@dataclass
class ActivationRow:
    """Событие включения ревизии (каждое включение — отдельная строка)."""

    block_id: str
    scope: str
    kind: str                      # ACTIVATION_KINDS
    outcome: str                   # ACTIVATION_OUTCOMES
    revision_id: str = ""
    factory_revision_applied: str = ""
    chat_id: int | None = None
    release_id: str = ""
    actor: str = ""
    detail_code: str = ""


@dataclass
class AppliedState:
    """Указатель последней применённой активации (applied | skipped_same)."""

    revision_id: str
    factory_revision_applied: str
    kind: str = ""
    activation_id: int = 0


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")


def _parse_ts(value: str | None) -> datetime.datetime | None:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value))
    except Exception:
        return None


def _scope_key(scope: str, chat_id: int | None) -> tuple:
    return (scope, int(chat_id) if chat_id is not None else None)


# ═══════════════════════════════════════════════════════════════════════════
# Ошибки и hook полномочий
# ═══════════════════════════════════════════════════════════════════════════

class JournalUnavailable(RuntimeError):
    """Журнал недоступен (PG down / пул отсутствует) — честный no-op."""


class PromptJournalError(RuntimeError):
    """Ошибка проводки релиза (срыв пакета: ни один ключ не изменён)."""


class PromptPermissionError(PermissionError):
    """Отказ проверки полномочий на операцию с ревизиями (EVOL-017 hook)."""


#: Hook полномочий сервисного API: ``(actor, action, context) -> bool``.
#: EVOL-017 HTTP-слой ОБЯЗАН установить RBAC-проверку; без установленного
#: checker'а сервис требует непустой actor и пишет аудит-событие.
PermissionChecker = Callable[[str, str, dict], bool]
_permission_checker: PermissionChecker | None = None


def set_permission_checker(checker: PermissionChecker | None) -> None:
    """Установить/снять hook полномочий (вызывает HTTP-слой EVOL-017)."""
    global _permission_checker
    _permission_checker = checker


def check_permission(actor: str, action: str, **ctx) -> None:
    """Проверить полномочия; бросает :class:`PromptPermissionError`."""
    if _permission_checker is not None:
        if not _permission_checker(str(actor or ""), action, dict(ctx)):
            raise PromptPermissionError(
                f"permission denied: {action} for actor={actor!r}")
        return
    if not str(actor or "").strip():
        raise PromptPermissionError(
            f"{action}: actor required (permission hook not installed)")
    logger.info("[prompt_release] permission (service rule) | actor=%s | "
                "action=%s | ctx=%s", actor, action, ctx)


# ═══════════════════════════════════════════════════════════════════════════
# In-memory стор (тесты): та же семантика, откат пакета, инъекция сбоев
# ═══════════════════════════════════════════════════════════════════════════

class _JournalState:
    """Контейнер состояния стора: committed-снапшот или tx-overlay.

    Ревью F5 (эмуляция семантики соединений PG): на время транзакции
    ``_live`` указывает на КЛОН committed — записи транзакции невидимы
    снаружи до коммита и откатываются целиком при сбое; методы стора читают
    и пишут только через ``_live`` (один «коннект» на транзакцию).
    """

    __slots__ = ("revisions", "activations", "activation_seq", "bot_settings",
                 "chat_overrides", "retired_blocks", "notified_chats",
                 "revision_seq")

    def __init__(self) -> None:
        self.revisions: dict[str, RevisionRow] = {}
        self.activations: list[ActivationRow] = []
        self.activation_seq = 0
        self.bot_settings: dict[str, str] = {}
        self.chat_overrides: dict[int, dict[str, str]] = {}
        self.retired_blocks: set[str] = set()
        self.notified_chats: list[int] = []
        self.revision_seq: dict[str, int] = {}

    def clone(self) -> "_JournalState":
        copy = _JournalState()
        copy.revisions = {k: RevisionRow(**vars(r))
                          for k, r in self.revisions.items()}
        copy.activations = [ActivationRow(**vars(a))
                            for a in self.activations]
        copy.activation_seq = self.activation_seq
        copy.bot_settings = dict(self.bot_settings)
        copy.chat_overrides = {c: dict(o)
                               for c, o in self.chat_overrides.items()}
        copy.retired_blocks = set(self.retired_blocks)
        copy.notified_chats = list(self.notified_chats)
        copy.revision_seq = dict(self.revision_seq)
        return copy


class MemoryPromptJournal:
    """Фейковый стор журнала: контракт PG-стора без реального PostgreSQL.

    Транзакционная семантика как у PG (ревью F5): на время ``transaction()``
    все методы работают на клоне состояния (``_live``); коммит публикует клон,
    откат отбрасывает целиком. ``fail_at`` — имя шага для инъекции сбоя
    (``ensure``, ``tx_enter``, ``insert_revision``, ``insert_activation``,
    ``tx_exit``): тесты крэша mid-apply проверяют, что пакет откатился целиком.
    """

    def __init__(self) -> None:
        self._committed = _JournalState()
        self._live = self._committed
        self.ensure_called = 0
        self.fail_at: str | None = None
        self._tx_conn = None
        self._lock = asyncio.Lock()

    # — доступ к состоянию (committed или tx-overlay через _live) —
    @property
    def revisions(self) -> dict[str, RevisionRow]:
        return self._live.revisions

    @property
    def activations(self) -> list[ActivationRow]:
        return self._live.activations

    @property
    def bot_settings(self) -> dict[str, str]:
        return self._live.bot_settings

    @property
    def chat_overrides(self) -> dict[int, dict[str, str]]:
        return self._live.chat_overrides

    @property
    def retired_blocks(self) -> set[str]:
        return self._live.retired_blocks

    @property
    def notified_chats(self) -> list[int]:
        return self._live.notified_chats

    # — инфраструктура —
    async def ensure_journal(self) -> bool:
        self.ensure_called += 1
        if self.fail_at == "ensure":
            raise JournalUnavailable("injected failure: ensure")
        return True

    def apply_lock(self):
        return self._lock

    class _Tx:
        def __init__(self, store: "MemoryPromptJournal") -> None:
            self.store = store

        async def __aenter__(self):
            store = self.store
            if store.fail_at == "tx_enter":
                raise PromptJournalError("injected failure: tx_enter")
            # Один «коннект» на транзакцию: _live = клон committed; записи
            # транзакции невидимы снаружи до коммита (семантика PG, ревью F5).
            store._tx_conn = object()
            store._live = store._committed.clone()
            return store

        async def __aexit__(self, exc_type, exc, tb):
            store = self.store
            try:
                if exc_type is not None:
                    return False          # rollback: клон отбрасывается
                if store.fail_at == "tx_exit":
                    raise PromptJournalError("injected failure: tx_exit")
                store._committed = store._live   # commit
            finally:
                store._live = store._committed
                store._tx_conn = None
            return False

    def transaction(self):
        return MemoryPromptJournal._Tx(self)

    # — чтение состояния —
    async def read_applied(self, block_id: str, scope: str,
                           chat_id: int | None) -> AppliedState | None:
        found = None
        for idx, row in enumerate(self.activations):
            if (row.block_id == block_id and row.outcome in
                    ("applied", "skipped_same")
                    and _scope_key(row.scope, row.chat_id)
                    == _scope_key(scope, chat_id)):
                found = (idx, row)
        if found is None:
            return None
        idx, row = found
        return AppliedState(revision_id=row.revision_id,
                            factory_revision_applied=row.factory_revision_applied,
                            kind=row.kind, activation_id=idx + 1)

    async def has_import(self, block_id: str, scope: str,
                         chat_id: int | None) -> bool:
        for row in self.revisions.values():
            if (row.block_id == block_id and row.origin == "legacy"
                    and _scope_key(row.scope, row.chat_id)
                    == _scope_key(scope, chat_id)):
                return True
        return any(row.block_id == block_id and row.kind == "legacy_import"
                   and _scope_key(row.scope, row.chat_id)
                   == _scope_key(scope, chat_id)
                   for row in self.activations)

    async def get_revision(self, revision_id: str) -> RevisionRow | None:
        row = self.revisions.get(revision_id)
        return RevisionRow(**vars(row)) if row is not None else None

    async def known_block_ids(self) -> set[str]:
        return {row.block_id for row in self.revisions.values()}

    async def list_revisions(self, block_id: str, chat_id: int | None = None,
                             *, include_retired: bool = True,
                             scope: str = "global") -> list:
        rows = [RevisionRow(**vars(r)) for r in self.revisions.values()
                if r.block_id == block_id
                and _scope_key(r.scope, r.chat_id)
                == _scope_key(scope, chat_id)
                and (include_retired or not r.retired)]
        rows.sort(key=lambda r: (r.created_at, r.revision_id))
        return rows

    async def list_activations(self, block_id: str,
                               chat_id: int | None = None,
                               limit: int = 50,
                               scope: str = "global") -> list[ActivationRow]:
        rows = [ActivationRow(**vars(a)) for a in self.activations
                if a.block_id == block_id
                and _scope_key(a.scope, a.chat_id)
                == _scope_key(scope, chat_id)]
        rows.reverse()
        return rows[:limit]

    # — запись —
    async def insert_revision(self, row: RevisionRow,
                              created_at: str | None = None) -> bool:
        if self.fail_at == "insert_revision":
            raise PromptJournalError("injected failure: insert_revision")
        if row.revision_id in self.revisions:
            return False
        # Микросекундная метка: порядок ревизий внутри секунды значим для
        # классификации rollback/forward (PG now() даёт микросекунды).
        row.created_at = created_at or datetime.datetime.now(
            datetime.timezone.utc).isoformat()
        self.revisions[row.revision_id] = row
        self._live.revision_seq[row.revision_id] = \
            len(self._live.revision_seq) + 1
        return True

    async def revision_precedes(self, revision_id: str,
                                other_id: str) -> bool | None:
        """Целевая ревизия создана РАНЬШЕ другой (порядок вставки журнала)."""
        seq_a = self._live.revision_seq.get(revision_id)
        seq_b = self._live.revision_seq.get(other_id)
        if seq_a is None or seq_b is None:
            return None
        return seq_a < seq_b

    async def insert_activation(self, row: ActivationRow) -> int:
        if self.fail_at == "insert_activation":
            raise PromptJournalError("injected failure: insert_activation")
        self._live.activation_seq += 1
        self.activations.append(row)
        return self._live.activation_seq

    async def mark_retired(self, block_ids: Iterable[str]) -> int:
        changed = 0
        for block_id in block_ids:
            self.retired_blocks.add(block_id)
            for row in self.revisions.values():
                if row.block_id == block_id and not row.retired:
                    row.retired = True
                    changed += 1
        return changed

    # — активные значения —
    async def read_global(self, pg_key: str) -> str | None:
        value = self.bot_settings.get(pg_key)
        return None if value is None else str(value)

    async def write_global(self, pg_key: str, value: str) -> None:
        self.bot_settings[pg_key] = value

    async def iter_chat_overrides(self, pg_key: str) -> list[tuple[int, str]]:
        out = []
        for chat_id, overrides in self.chat_overrides.items():
            if pg_key in overrides:
                out.append((chat_id, str(overrides[pg_key])))
        return sorted(out)

    async def remove_chat_override(self, chat_id: int, pg_key: str) -> bool:
        overrides = self.chat_overrides.get(chat_id) or {}
        if pg_key not in overrides:
            return False
        overrides.pop(pg_key, None)
        return True

    async def set_chat_override(self, chat_id: int, pg_key: str,
                                value: str) -> bool:
        self.chat_overrides.setdefault(chat_id, {})[pg_key] = value
        return True

    async def notify_chat(self, chat_id: int) -> None:
        self.notified_chats.append(chat_id)


# ═══════════════════════════════════════════════════════════════════════════
# PG-стор журнала (тот же пул, что и bot_settings)
# ═══════════════════════════════════════════════════════════════════════════

class PgPromptJournal:
    """PG-стор журнала. ``ensure_journal`` лениво выполняет идемпотентный DDL."""

    def __init__(self, pool) -> None:
        self._pool = pool
        self._ready = False
        self._tx_conn = None

    @classmethod
    def from_cache(cls, cache) -> "PgPromptJournal | None":
        pool = None
        pg = getattr(cache, "pg", None)
        if pg is not None:
            pool = getattr(pg, "pool", None)
        return cls(pool) if pool is not None else None

    async def ensure_journal(self) -> bool:
        if self._ready:
            return True
        async with self._pool.acquire() as conn:
            for statement in JOURNAL_DDL:
                await conn.execute(statement)
        self._ready = True
        return True

    async def _run_on_conn(self, fn):
        """Выполнить операцию ЖУРНАЛА на правильном соединении.

        Ревью F5: внутри транзакции применения все чтения/записи идут через
        ``_tx_conn`` (иначе читается чужой снапшот — собственные незакоммиченные
        записи невидимы, план считается по устаревшему состоянию, а
        ``mark_retired`` фиксировался бы отдельным автокоммитом до коммита
        релиза). Вне транзакции — короткоживущий коннект пула.
        """
        if self._tx_conn is not None:
            return await fn(self._tx_conn)
        async with self._pool.acquire() as conn:
            return await fn(conn)

    def apply_lock(self):
        # Сериализация применений — advisory xact lock ВНУТРИ транзакции;
        # отказ лока (ошибка БД) поднимается из ``transaction().__aenter__``
        # и отвергает ВЕСЬ пакет (ревью F5: никакого тихого skip).
        class _NullLock:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        return _NullLock()

    class _PgTx:
        def __init__(self, store: "PgPromptJournal") -> None:
            self.store = store
            self.conn = None

        async def __aenter__(self):
            self.conn = await self.store._pool.acquire()
            self._tx = self.conn.transaction()
            await self._tx.start()
            self.store._tx_conn = self.conn
            try:
                # Ревью F5: сбой advisory-лока НЕ проглатывается — применение
                # пакета refuse (исключение уходит вызывающему).
                await self.conn.execute(APPLY_LOCK_SQL)
            except Exception:
                # __aexit__ при сбое __aenter__ не вызывается — прибираемся:
                # транзакция откатывается, коннект возвращается в пул.
                try:
                    await self._tx.rollback()
                finally:
                    self.store._tx_conn = None
                    await self.store._pool.release(self.conn)
                    self.conn = None
                    logger.error("[prompt_release] advisory lock не взят — "
                                 "применение пакета ОТКЛОНЕНО (fail-closed)",
                                 exc_info=True)
                raise
            return self.store

        async def __aexit__(self, exc_type, exc, tb):
            try:
                if exc_type is None:
                    await self._tx.commit()
                else:
                    await self._tx.rollback()
            finally:
                self.store._tx_conn = None
                await self.store._pool.release(self.conn)
                self.conn = None
            return False

    def transaction(self):
        return PgPromptJournal._PgTx(self)

    async def read_applied(self, block_id: str, scope: str,
                           chat_id: int | None) -> AppliedState | None:
        async def _run(conn):
            return await conn.fetchrow(_LAST_APPLIED_SQL, block_id, scope,
                                       chat_id)
        row = await self._run_on_conn(_run)
        if row is None:
            return None
        return AppliedState(revision_id=row["revision_id"] or "",
                            factory_revision_applied=(
                                row["factory_revision_applied"] or ""),
                            kind=row["kind"] or "",
                            activation_id=int(row["activation_id"]))

    async def has_import(self, block_id: str, scope: str,
                         chat_id: int | None) -> bool:
        async def _run(conn):
            if await conn.fetchval(_HAS_IMPORT_SQL, block_id, scope, chat_id):
                return True
            return bool(await conn.fetchval(_HAS_CUTOVER_SQL, block_id, scope,
                                            chat_id))
        return await self._run_on_conn(_run)

    async def get_revision(self, revision_id: str) -> RevisionRow | None:
        async def _run(conn):
            return await conn.fetchrow(_GET_REVISION_SQL, revision_id)
        row = await self._run_on_conn(_run)
        if row is None:
            return None
        return RevisionRow(
            revision_id=row["revision_id"], block_id=row["block_id"],
            scope=row["scope"], origin=row["origin"],
            content_sha12=row["content_sha12"], body=row["body"],
            pg_key=row["pg_key"] or "", chat_id=row["chat_id"],
            factory_revision=row["factory_revision"] or "",
            schema_compat=row["schema_compat"] or "",
            release_id=row["release_id"] or "", actor=row["actor"] or "",
            reason=row["reason"] or "",
            source_updated_at=row["source_updated_at"] or "",
            retired=bool(row["retired"]),
            created_at=str(row["created_at"]))

    async def known_block_ids(self) -> set[str]:
        await self.ensure_journal()

        async def _run(conn):
            return await conn.fetch(_KNOWN_BLOCK_IDS_SQL)
        rows = await self._run_on_conn(_run)
        return {r["block_id"] for r in rows}

    async def revision_precedes(self, revision_id: str,
                                other_id: str) -> bool | None:
        """Целевая ревизия создана РАНЬШЕ другой (по created_at PG)."""
        a = await self.get_revision(revision_id)
        b = await self.get_revision(other_id)
        if a is None or b is None:
            return None
        ta, tb = _parse_ts(a.created_at), _parse_ts(b.created_at)
        if ta is None or tb is None:
            return None
        if ta == tb:
            return None        # неразличимый порядок — honest fallback
        return ta < tb

    async def list_revisions(self, block_id: str, chat_id: int | None = None,
                             *, include_retired: bool = True) -> list:
        await self.ensure_journal()

        async def _run(conn):
            return await conn.fetch(_LIST_REVISIONS_SQL, block_id, chat_id)
        rows = await self._run_on_conn(_run)
        out = []
        for row in rows:
            if not include_retired and row["retired"]:
                continue
            out.append(RevisionRow(
                revision_id=row["revision_id"], block_id=row["block_id"],
                scope=row["scope"], origin=row["origin"],
                content_sha12=row["content_sha12"], body="",
                pg_key=row["pg_key"] or "", chat_id=row["chat_id"],
                factory_revision=row["factory_revision"] or "",
                schema_compat=row["schema_compat"] or "",
                release_id=row["release_id"] or "",
                actor=row["actor"] or "", reason=row["reason"] or "",
                source_updated_at=row["source_updated_at"] or "",
                retired=bool(row["retired"]),
                created_at=str(row["created_at"])))
        return out

    async def list_activations(self, block_id: str,
                               chat_id: int | None = None,
                               limit: int = 50) -> list[ActivationRow]:
        await self.ensure_journal()

        async def _run(conn):
            return await conn.fetch(_LIST_ACTIVATIONS_SQL, block_id, chat_id,
                                    limit)
        rows = await self._run_on_conn(_run)
        return [ActivationRow(
            block_id=r["block_id"], scope=r["scope"], kind=r["kind"],
            outcome=r["outcome"], revision_id=r["revision_id"] or "",
            factory_revision_applied=r["factory_revision_applied"] or "",
            chat_id=r["chat_id"], release_id=r["release_id"] or "",
            actor=r["actor"] or "", detail_code=r["detail_code"] or "")
            for r in rows]

    async def insert_revision(self, row: RevisionRow,
                              created_at: str | None = None) -> bool:
        async def _run(conn):
            return await conn.execute(
                _INSERT_REVISION_SQL, row.revision_id, row.block_id,
                row.pg_key, row.scope, row.chat_id, row.origin,
                row.content_sha12, row.body, row.factory_revision,
                row.schema_compat, row.release_id, row.actor, row.reason,
                row.source_updated_at, _parse_ts(created_at))
        status = await self._run_on_conn(_run)
        return status.endswith("INSERT 0 1")

    async def insert_activation(self, row: ActivationRow) -> int:
        async def _run(conn):
            return await conn.fetchval(
                _INSERT_ACTIVATION_SQL, row.block_id, row.scope,
                row.chat_id, row.revision_id, row.factory_revision_applied,
                row.kind, row.outcome, row.release_id, row.actor,
                row.detail_code)
        activation_id = await self._run_on_conn(_run)
        return int(activation_id)

    async def mark_retired(self, block_ids: Iterable[str]) -> int:
        ids = sorted(set(block_ids or ()))
        if not ids:
            return 0

        async def _run(conn):
            # Ревью F5: внутри применения — через tx-коннект (фиксируется
            # КОММИТОМ релиза, никакого отдельного автокоммита до него).
            return await conn.execute(_MARK_RETIRED_SQL, ids)
        status = await self._run_on_conn(_run)
        try:
            return int(status.split()[-1])
        except Exception:      # pragma: no cover
            return 0

    async def read_global(self, pg_key: str) -> str | None:
        async def _run(conn):
            return await conn.fetchrow(_SELECT_BOT_SETTING_SQL, pg_key)
        row = await self._run_on_conn(_run)
        return None if row is None else (row["text"] or "")

    async def write_global(self, pg_key: str, value: str) -> None:
        if self._tx_conn is None:       # pragma: no cover — контракт транзакции
            raise PromptJournalError("write_global outside release transaction")
        await self._tx_conn.execute(_UPSERT_BOT_SETTING_SQL, pg_key,
                                    json.dumps(value), "prompts")

    async def iter_chat_overrides(self, pg_key: str) -> list[tuple[int, str]]:
        async def _run(conn):
            return await conn.fetch(_SELECT_CHAT_OVERRIDES_SQL, pg_key)
        rows = await self._run_on_conn(_run)
        return [(int(r["chat_id"]), r["value"]) for r in rows]

    async def remove_chat_override(self, chat_id: int, pg_key: str) -> bool:
        if self._tx_conn is None:       # pragma: no cover
            raise PromptJournalError(
                "remove_chat_override outside release transaction")
        status = await self._tx_conn.execute(_DROP_CHAT_OVERRIDE_SQL, chat_id,
                                             pg_key)
        return not status.endswith("0")

    async def set_chat_override(self, chat_id: int, pg_key: str,
                                value: str) -> bool:
        if self._tx_conn is None:       # pragma: no cover
            raise PromptJournalError(
                "set_chat_override outside release transaction")
        status = await self._tx_conn.execute(_SET_CHAT_OVERRIDE_SQL, chat_id,
                                             pg_key, json.dumps(value))
        return not status.endswith("0")

    async def notify_chat(self, chat_id: int) -> None:
        if self._tx_conn is not None:   # внутри транзакции: NOTIFY на commit
            await self._tx_conn.execute(_NOTIFY_CHAT_SQL, str(chat_id))


def default_journal(cache):
    """Стор по умолчанию: PG-журнал из пула ConfigCache (или ``None``).

    Пул обязан быть настоящим asyncpg-пулом: тестовые SQLite-двойники
    (``_SqliteConn``) проходят duck-typing DDL, но не реализуют asyncpg-API —
    с ними журнал честно недоступен (no-op), а не падает на середине.
    """
    if cache is None or not getattr(cache, "pg_available", False):
        return None
    store = PgPromptJournal.from_cache(cache)
    if store is None:
        return None
    pool = store._pool
    if not getattr(type(pool), "__module__", "").startswith("asyncpg"):
        return None
    return store


# ═══════════════════════════════════════════════════════════════════════════
# Проводка релиза
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BlockReleaseResult:
    """Итог применения релиза для одного (блок, scope, chat) — без текстов."""

    block_id: str
    scope: str
    chat_id: int | None = None
    action: str = ""
    outcome: str = ""
    detail_code: str = ""
    revision_id: str = ""
    factory_revision_applied: str = ""

    def as_log(self) -> str:
        return (f"block={self.block_id} | scope={self.scope}"
                + (f" | chat={self.chat_id}" if self.chat_id is not None
                   else "")
                + f" | action={self.action} | outcome={self.outcome}"
                + (f" | detail={self.detail_code}" if self.detail_code else "")
                + (f" | rev={self.revision_id}" if self.revision_id else "")
                + (f" | factory_rev={self.factory_revision_applied}"
                   if self.factory_revision_applied else ""))


def _release_blocks(blocks: Iterable[str] | None = None) -> tuple:
    """Блоки релизной активации: PG-ключи + кодовые блоки с меткой.

    Кодовые блоки НЕ копируются в ``bot_settings`` (активный текст — кодовая
    константа; контракт §1.5): для них пишется только книжная ревизия
    ``origin=factory`` при смене метки. Управляемые сообщения без метки в
    релизной активации не участвуют (их версионируют печати + CI).
    """
    selected = pr.all_blocks()
    if blocks is not None:
        wanted = set(blocks)
        selected = tuple(s for s in selected if s.block_id in wanted)
    return tuple(s for s in sorted(selected, key=lambda s: s.block_id)
                 if (s.pg_key or pr.sealed_factory_revision(s.block_id))
                 and pr.factory_text(s.block_id))


async def apply_release(cache, *, release_id: str, store=None,
                        blocks: Iterable[str] | None = None) -> dict:
    """Применить заводской релиз промптов (стартовая проводка; контракт §1.4).

    Детерминизм:
      * рестарт с той же применённой меткой → no-op (ни строки, ни записи);
      * новая метка при целой печати → заводской текст активен даже поверх
        ручной правки (прежний текст остаётся ревизией);
      * первый запуск (нет legacy-снимка/cutover-строки) → снимок, затем
        активация (``release_id=evol-016-cutover``);
      * печать не цела → fail-closed: ERROR, БД не тронута (весь пакет);
      * расхождение журнала и ``bot_settings`` → ERROR ``activation_drift``,
        источник истины на этот старт — PG-значение; заводской текст заново
        не включается до новой метки;
      * два воркера → advisory-лок (PG) / ``asyncio.Lock`` (memory): второй
        видит применённую ревизию и не пишет дубль.

    PG недоступен → skip с INFO (как прежний ``migrate_prompt_canons``):
    активация «из констант поверх журнала» запрещена. Падение до commit —
    в БД ничего нет, следующий старт повторяет применение; падение после —
    повтор видит применённую ревизию и делает no-op.
    """
    store = store if store is not None else default_journal(cache)
    if store is None:
        logger.info("[prompt_release] skip: PG/журнал недоступен — активация "
                    "из констант запрещена (fail-open runtime)")
        return {"applied": False, "reason": "journal_unavailable",
                "release_id": release_id, "results": []}
    try:
        await store.ensure_journal()
    except Exception:
        logger.warning("[prompt_release] журнал недоступен (DDL) — skip",
                       exc_info=True)
        return {"applied": False, "reason": "journal_unavailable",
                "release_id": release_id, "results": []}

    # Целостность печатей — ДО транзакции (fail-closed на весь пакет).
    # `seal_unknown_block` (остаток печати снятого с регистрации блока) не
    # блокирует релиз: у снятого блока нет runtime-текста, это bookkeeping.
    broken = {bid: code for bid, code in pr.seal_integrity().items()
              if code != "seal_unknown_block"}
    stale_seals = sorted(bid for bid, code in pr.seal_integrity().items()
                         if code == "seal_unknown_block")
    if stale_seals:
        logger.info("[prompt_release] устаревшие печати снятых блоков "
                    "(bookkeeping): %s", stale_seals)
    if broken:
        for block_id, code in sorted(broken.items()):
            logger.error(
                "[prompt_release] integrity_label_unchanged | block=%s | "
                "code=%s | factory_revision=%s — запись в журнал запрещена",
                block_id, code, pr.sealed_factory_revision(block_id))
        logger.error("[prompt_release] пакет НЕ применён: сломаны печати "
                     "(%d) — бампните метку и печать одним коммитом",
                     len(broken))
        return {"applied": False, "reason": "integrity_label_unchanged",
                "release_id": release_id, "integrity": dict(broken),
                "results": []}

    specs = _release_blocks(blocks)
    results: list[BlockReleaseResult] = []
    doc_state: dict[str, dict] = {}   # документ Core в рамках транзакции
    async with store.apply_lock():
        async with store.transaction() as tx:
            try:
                orphans = await _import_provenance_history(store, cache=cache)
                for spec in specs:
                    results.extend(await _apply_block_release(
                        store, spec, cache, release_id=release_id,
                        doc_state=doc_state))
                retired = await _mark_retired_blocks(store)
            except Exception:
                # Срыв пакета: транзакция откатится целиком (§1.4).
                logger.error("[prompt_release] пакет отменён (rollback) | "
                             "release=%s", release_id, exc_info=True)
                raise
        # Транзакция закоммичена: обновляем память кэша и чат-кэши.
        await _refresh_runtime_caches(cache, store, results)

    applied_count = sum(1 for r in results if r.outcome == "applied")
    for row in results:
        if row.outcome in ("applied", "skipped_empty"):
            logger.info("[prompt_release] activation | release=%s | %s",
                        release_id, row.as_log())
    # Политика активна: persisted-текст PG = эффективный слой (§1.6);
    # история character.prompt_history заморожена (импорт выполнен).
    pr.set_release_policy_active(True)
    pr.set_retired_blocks(retired)
    _freeze_history()
    if orphans:
        logger.info("[prompt_release] осиротевшие block_id в старой истории "
                    "(в реестре отсутствуют): %s", sorted(orphans))
    logger.info("[prompt_release] релиз применён | release=%s | blocks=%d | "
                "changed=%d | retired=%d", release_id, len(specs),
                applied_count, len(retired))
    return {"applied": True, "release_id": release_id, "results": results,
            "changed": applied_count, "retired_blocks": sorted(retired),
            "orphan_history_blocks": sorted(orphans)}


def _freeze_history() -> None:
    """Заморозить дописывание ``character.prompt_history`` (контракт §1.2)."""
    try:
        from services import prompt_factory as pf
        pf.freeze_history()
    except Exception:          # pragma: no cover — фриз не роняет старт
        logger.debug("[prompt_release] history freeze failed", exc_info=True)


async def _import_provenance_history(store, cache=None) -> set[str]:
    """Одноразовый перенос ``character.prompt_history`` в журнал (§1.6).

    ``items`` → ревизии (owner_edit→manual, factory_reset→factory,
    backup_restore→restored, legacy_strip→legacy); время — из поля ``at``
    записи, автор не выдумывается. Дубликаты невозможны (revision_id).
    Возвращает осиротевшие block_id (нет в реестре).
    """
    try:
        doc = pr.provenance_doc(cache)
    except Exception:          # pragma: no cover — старая история не роняет
        return set()
    if not isinstance(doc, dict):
        return set()
    orphans: set[str] = set()
    known = {s.block_id for s in pr.all_blocks()}
    kind_map = {"owner_edit": "manual", "factory_reset": "factory",
                "backup_restore": "restored", "legacy_strip": "legacy"}
    for block_id, entries in (doc.get("items") or {}).items():
        block_id = str(block_id)
        spec = pr.block(block_id)
        if spec is None:
            if block_id in known:
                continue
            orphans.add(block_id)
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            body = entry.get("text")
            if not isinstance(body, str) or not body:
                continue
            origin = kind_map.get(str(entry.get("kind") or ""), "legacy")
            await _insert_revision_once(
                store, spec, origin=origin, body=body, scope="global",
                chat_id=None,
                factory_revision=(pr.sealed_factory_revision(block_id)
                                  if origin == "factory" else ""),
                actor=str(entry.get("by") or ""),
                reason=str(entry.get("reason") or "history_import"),
                created_at=str(entry.get("at") or "") or None)
    for block_id, entry in (doc.get(pr.PROVENANCE_MAP_FIELD) or {}).items():
        # Провенанс-факт активации: байт нет — ревизию не выдумываем, но
        # осиротевший block_id фиксируем честно.
        block_id = str(block_id)
        if pr.block(block_id) is None and block_id not in known:
            orphans.add(block_id)
    return orphans


async def _insert_revision_once(store, spec, *, origin: str, body: str,
                                scope: str, chat_id: int | None,
                                factory_revision: str = "", actor: str = "",
                                reason: str = "", release_id: str = "",
                                schema_compat: str = "",
                                source_updated_at: str = "",
                                created_at: str | None = None) -> RevisionRow:
    row = RevisionRow(
        revision_id=pr.revision_id_for(spec.block_id, scope, chat_id, origin,
                                       pr.sha12(body)),
        block_id=spec.block_id, scope=scope, origin=origin,
        content_sha12=pr.sha12(body), body=body, pg_key=spec.pg_key or "",
        chat_id=chat_id, factory_revision=factory_revision,
        schema_compat=schema_compat, release_id=release_id, actor=actor,
        reason=reason, source_updated_at=source_updated_at)
    await store.insert_revision(row, created_at=created_at)
    return row


async def _apply_block_release(store, spec, cache, *,
                               release_id: str,
                               doc_state: dict[str, dict] | None = None
                               ) -> list[BlockReleaseResult]:
    """Автомат контракта §1.4 для одного блока (global + его chat-override'ы)."""
    results: list[BlockReleaseResult] = []
    seal = pr.FACTORY_REVISION_SEALS.get(spec.block_id) or ("", "")
    code_label = seal[0]
    if not code_label:
        return results          # управляемое сообщение без метки — вне релиза
    factory_body = pr.factory_text(spec.block_id)
    doc_state = doc_state if doc_state is not None else {}

    if spec.pg_key:
        current = _spec_current_text(spec, cache)
        current_doc: dict | None = None
        if spec.pg_doc_field:
            # База документа: результат записи в ЭТОЙ транзакции (второе
            # поле Core не затирает первое), иначе текущий документ слоя.
            current_doc = doc_state.get(spec.pg_key)
            if current_doc is None:
                current_doc = _spec_current_doc(spec, cache)
        state = await store.read_applied(spec.block_id, "global", None)
        await _apply_scope_release(
            store, spec, scope="global", chat_id=None, code_label=code_label,
            sealed_sha=seal[1], factory_body=factory_body, current=current,
            cache=cache, release_id=release_id, results=results, state=state,
            current_doc=current_doc, doc_state=doc_state,
            has_import=(await store.has_import(spec.block_id, "global", None))
            or state is not None)
        # §1.5: существующие chat-override'ы этого ключа.
        for chat_id, override in await store.iter_chat_overrides(spec.pg_key):
            chat_state = await store.read_applied(spec.block_id, "chat",
                                                  chat_id)
            await _apply_scope_release(
                store, spec, scope="chat", chat_id=chat_id,
                code_label=code_label, sealed_sha=seal[1],
                factory_body=factory_body, current=override, cache=cache,
                release_id=release_id, results=results, state=chat_state,
                has_import=(await store.has_import(spec.block_id, "chat",
                                                   chat_id))
                or chat_state is not None)
    else:
        # Кодовый блок: активный текст — кодовая константа, пишем только
        # книжную ревизию при смене метки (второго хранилища нет, §1.5).
        # Рестарт с той же меткой — no-op: указатель в scope ``code``.
        code_state = await store.read_applied(spec.block_id, "code", None)
        await _apply_scope_release(
            store, spec, scope="code", chat_id=None, code_label=code_label,
            sealed_sha=seal[1], factory_body=factory_body, current=None,
            cache=cache, release_id=release_id, results=results,
            state=code_state, has_import=code_state is not None)
    return results


def _spec_current_text(spec, cache) -> str:
    """Фактический активный текст глобального слоя (значение или поле док-та)."""
    try:
        if cache is None:
            return ""
        raw = cache.get(spec.pg_key, None)
        if raw is None:
            return ""
        if not spec.pg_doc_field:
            return str(raw) if isinstance(raw, str) else ""
        from services.prompt_factory import _doc_from_raw
        return pr.doc_field_text(_doc_from_raw(raw), spec.pg_doc_field)
    except Exception:          # pragma: no cover — PG down: cutover отложится
        return ""


def _spec_current_doc(spec, cache) -> dict:
    """Текущий JSON-документ блока-поля (Core): read-modify-write база.

    Документ живёт в слое ``bot_settings`` (кэш — его память); пишем поле,
    не теряя остальные поля и выбор владельца.
    """
    try:
        from services.prompt_factory import _doc_from_raw
        raw = cache.get(spec.pg_key, None) if cache is not None else None
        return _doc_from_raw(raw)
    except Exception:          # pragma: no cover
        return {}


async def _apply_scope_release(store, spec, *, scope: str,
                               chat_id: int | None, code_label: str,
                               sealed_sha: str, factory_body: str,
                               current: str | None, cache,
                               release_id: str,
                               results: list[BlockReleaseResult],
                               state: AppliedState | None,
                               has_import: bool,
                               current_doc: dict | None = None,
                               doc_state: dict[str, dict] | None = None
                               ) -> None:
    """Один прогон автомата для (block, scope, chat_id). Контракт §1.3/§1.4."""
    plan = pr.activation_plan(
        code_label=code_label, sealed_sha=sealed_sha,
        text_sha12=pr.sha12(factory_body),
        applied_factory_revision=(state.factory_revision_applied
                                  if state is not None else ""),
        has_import=has_import)

    if plan.action == pr.PLAN_NOOP:
        # Рестарт: ни строки, ни записи — ручная правка остаётся активной.
        # Ревью F1: дрейф обнаруживается и на рестарте (метка не новее
        # применённой) — один ERROR + снимок, активации НЕТ: рестарт с
        # неизменённой меткой остаётся истинным no-op (снимок известен
        # журналу, повторные рестарты молчат).
        if state is not None and state.revision_id and current:
            drift = await _check_activation_drift(
                store, spec, scope, chat_id, state, current, release_id,
                activate_after=False)
            if drift is not None:
                results.append(drift)
                results.append(BlockReleaseResult(
                    spec.block_id, scope, chat_id, plan.action,
                    "skipped_same", plan.reason,
                    factory_revision_applied=plan.code_revision))
                return
        results.append(BlockReleaseResult(
            spec.block_id, scope, chat_id, plan.action, "skipped_same",
            plan.reason, factory_revision_applied=plan.code_revision))
        return
    if plan.action == pr.PLAN_INTEGRITY_REJECT:  # pragma: no cover —
        # печати проверяются пакетно до транзакции; defensive-ветка.
        results.append(BlockReleaseResult(
            spec.block_id, scope, chat_id, plan.action, "failed",
            plan.reason))
        return

    # Ревью F1: дрейф при НОВОЙ метке — снимок и активация заводской ревизии
    # в ЭТОЙ ЖЕ транзакции (второй старт для применения не нужен).
    if state is not None and state.revision_id and current:
        drift = await _check_activation_drift(
            store, spec, scope, chat_id, state, current, release_id,
            activate_after=True)
        if drift is not None:
            results.append(drift)   # ERROR-аудит + снимок; активация ниже

    if current is None:
        current = ""

    if plan.action == pr.PLAN_LEGACY_CUTOVER and spec.pg_key:
        # Снимок ДО первой записи заводского текста (§1.4): даже байты,
        # равные заводским, — origin=legacy (UI не подписывает это «Изменена
        # в админке»); пустой ключ → skipped_empty, автор не выдумывается.
        if current.strip():
            snapshot = await _insert_revision_once(
                store, spec, origin="legacy", body=current, scope=scope,
                chat_id=chat_id, actor="", reason="legacy_import",
                source_updated_at=_source_updated_at(spec, cache),
                release_id=release_id)
            await store.insert_activation(ActivationRow(
                block_id=spec.block_id, scope=scope, chat_id=chat_id,
                revision_id=snapshot.revision_id,
                factory_revision_applied="", kind="legacy_import",
                outcome="applied", release_id=release_id, actor="",
                detail_code="legacy_snapshot"))
            results.append(BlockReleaseResult(
                spec.block_id, scope, chat_id, "legacy_snapshot", "applied",
                "legacy_import", revision_id=snapshot.revision_id))
        else:
            await store.insert_activation(ActivationRow(
                block_id=spec.block_id, scope=scope, chat_id=chat_id,
                revision_id="", factory_revision_applied="",
                kind="legacy_import", outcome="skipped_empty",
                release_id=release_id, actor="", detail_code="legacy_empty"))
            results.append(BlockReleaseResult(
                spec.block_id, scope, chat_id, "legacy_snapshot",
                "skipped_empty", "legacy_import"))

    # Активация заводской ревизии (deploy / cutover).
    revision = await _insert_revision_once(
        store, spec, origin="factory", body=factory_body, scope=scope,
        chat_id=chat_id, factory_revision=plan.code_revision,
        reason="factory_release", release_id=release_id)
    outcome, detail = "applied", "factory_activate"
    if spec.pg_key:
        if current == factory_body:
            outcome, detail = "skipped_same", "factory_same"
        else:
            await _write_active_value(store, spec, scope, chat_id,
                                      factory_body, current_doc=current_doc,
                                      doc_state=doc_state)
    elif scope == "code":
        detail = "code_revision_recorded"
    await store.insert_activation(ActivationRow(
        block_id=spec.block_id, scope=scope, chat_id=chat_id,
        revision_id=revision.revision_id,
        factory_revision_applied=plan.code_revision,
        # Активация ЗНАЧЕНИЯ — явное событие релиза (deploy_activate) и на
        # cutover тоже; kind=legacy_import зарезервирован за строкой снимка.
        kind="deploy_activate",
        outcome=outcome, release_id=release_id, actor="", detail_code=detail))
    results.append(BlockReleaseResult(
        spec.block_id, scope, chat_id, plan.action, outcome, detail,
        revision_id=revision.revision_id,
        factory_revision_applied=plan.code_revision))

    # §1.5: новая метка снимает с эффективного пути устаревший chat-override
    # этого блока (текст уже в ревизии), иначе старый override прятал бы
    # новый заводской шаблон. Override, созданный ПОСЛЕ применения метки,
    # рестарт не снимает (ветка PLAN_NOOP выше).
    if scope == "chat" and spec.pg_key and plan.action in (
            pr.PLAN_ACTIVATE, pr.PLAN_LEGACY_CUTOVER):
        await store.remove_chat_override(int(chat_id), spec.pg_key)
        await store.notify_chat(int(chat_id))


def _source_updated_at(spec, cache) -> str:
    """``bot_settings.updated_at`` — только справочное поле снимка (§1.4)."""
    try:
        if cache is not None and hasattr(cache, "get_updated_at"):
            return str(cache.get_updated_at(spec.pg_key) or "")
    except Exception:          # pragma: no cover
        return ""
    return ""


async def _check_activation_drift(store, spec, scope, chat_id,
                                  state: AppliedState, current: str,
                                  release_id: str, *,
                                  activate_after: bool
                                  ) -> BlockReleaseResult | None:
    """Журнал говорит «applied», а активный текст другой → не угадывать (§1.4).

    Ревью F1: снимок делается всегда, а дальнейшее зависит от метки — при
    НОВОЙ метке (``activate_after=True``) заводская ревизия активируется в той
    же транзакции вызывающим; при неизменённой метке активации нет (рестарт —
    истинный no-op, снимок известен журналу, повторных ERROR не будет).
    """
    if not current.strip():
        return None             # пустой активный текст — не дрейф
    rev = await store.get_revision(state.revision_id)
    if rev is None or rev.content_sha12 == pr.sha12(current):
        return None
    # Текст уже известен журналу (правка без строки активации и т.п.) — не дрейф.
    for origin in pr.REVISION_ORIGINS:
        existing = await store.get_revision(
            pr.revision_id_for(spec.block_id, scope, chat_id, origin,
                               pr.sha12(current)))
        if existing is not None:
            return None
    disposition = ("снимок зафиксирован; заводская ревизия новой метки "
                   "активируется в этой же транзакции" if activate_after else
                   "метка не новее применённой — активации нет, рестарт "
                   "остаётся no-op")
    logger.error(
        "[prompt_release] activation_drift | block=%s | scope=%s | chat=%s | "
        "journal_rev=%s | journal_sha=%s | active_sha=%s — источник истины "
        "на этот старт: PG-значение (%s)", spec.block_id, scope, chat_id,
        state.revision_id, rev.content_sha12, pr.sha12(current), disposition)
    snapshot = await _insert_revision_once(
        store, spec, origin="legacy", body=current, scope=scope,
        chat_id=chat_id, actor="", reason="drift_recovery",
        release_id=release_id)
    await store.insert_activation(ActivationRow(
        block_id=spec.block_id, scope=scope, chat_id=chat_id,
        revision_id=snapshot.revision_id,
        factory_revision_applied=state.factory_revision_applied,
        kind="integrity_reject", outcome="failed", release_id=release_id,
        actor="", detail_code="activation_drift"))
    return BlockReleaseResult(
        spec.block_id, scope, chat_id, "drift_check", "failed",
        "activation_drift", revision_id=snapshot.revision_id,
        factory_revision_applied=state.factory_revision_applied)


async def _write_active_value(store, spec, scope: str, chat_id: int | None,
                              value: str,
                              current_doc: dict | None = None,
                              doc_state: dict[str, dict] | None = None
                              ) -> None:
    doc_state = doc_state if doc_state is not None else {}
    """Записать активное значение в той же транзакции (нет второго источника)."""
    if scope == "chat":
        await store.set_chat_override(int(chat_id), spec.pg_key, value)
        await store.notify_chat(int(chat_id))
        return
    if spec.pg_doc_field:
        # Поле документа Core: read-modify-write в транзакции; второе поле
        # цело; выбор detail_level владельца не меняется (set_level=False).
        # База документа: запись этой же транзакции (doc_state) → текущий
        # документ слоя (кэш) → документ стора.
        from services.prompt_factory import _doc_from_raw, _doc_with_field
        if current_doc is not None:
            doc = dict(current_doc)
        else:
            raw = await store.read_global(spec.pg_key)
            doc = _doc_from_raw(raw)
        doc = _doc_with_field(doc, spec.pg_doc_field, value, set_level=False)
        doc_state[spec.pg_key] = dict(doc)
        if isinstance(store, PgPromptJournal):
            if store._tx_conn is None:       # pragma: no cover
                raise PromptJournalError(
                    "doc write outside release transaction")
            await store._tx_conn.execute(_UPSERT_BOT_SETTING_SQL, spec.pg_key,
                                         json.dumps(doc), "content")
        else:
            # In-memory стор (тесты): документ живёт строкой JSON, как его
            # отдаёт PG (value #>> '{}'); чтение парсит _doc_from_raw.
            await store.write_global(spec.pg_key, json.dumps(doc))
        return
    await store.write_global(spec.pg_key, value)


async def _mark_retired_blocks(store) -> set[str]:
    """Снятые с регистрации блоки: ревизии читаются, ``retired=true`` (§1.6)."""
    try:
        journal_blocks = await store.known_block_ids()
    except Exception:          # pragma: no cover
        return set()
    registry_ids = {s.block_id for s in pr.all_blocks()}
    retired = {b for b in journal_blocks if b not in registry_ids}
    if retired:
        await store.mark_retired(retired)
    return retired


async def _refresh_runtime_caches(cache, store,
                                  results: list[BlockReleaseResult]) -> None:
    """После commit: память ConfigCache + инвалидация чат-кэшей (§1.4 п.4).

    В память кэша попадает НОВОЕ значение из журнала (PG-строка уже
    перезаписана транзакцией; память кэша могла быть устаревшей).
    """
    changed_globals: dict[str, str] = {}
    changed_chats: set[int] = set()
    for row in results:
        if row.outcome != "applied" or not row.revision_id:
            continue
        spec = pr.block(row.block_id)
        if spec is None or not spec.pg_key:
            continue
        if row.scope == "global":
            changed_globals[spec.pg_key] = spec.pg_doc_field
        elif row.chat_id is not None:
            changed_chats.add(int(row.chat_id))
    for pg_key, doc_field in sorted(changed_globals.items()):
        try:
            raw = await store.read_global(pg_key)
            if raw is None:
                continue
            value: object = json.loads(raw) if doc_field else raw
            if doc_field and not isinstance(value, dict):
                continue
            await cache.set(pg_key, value,
                            "content" if doc_field else "prompts")
        except Exception:      # pragma: no cover — память не роняет старт
            logger.warning("[prompt_release] кэш памяти не обновлён | "
                           "key=%s", pg_key, exc_info=True)
    if changed_chats:
        try:
            from services.chat_params import get_chat_params_cache
            chat_cache = get_chat_params_cache()
            if chat_cache is not None:
                for chat_id in sorted(changed_chats):
                    try:
                        await chat_cache.invalidate_chat(chat_id)
                    except Exception:      # pragma: no cover
                        logger.debug(
                            "[prompt_release] chat cache invalidate failed "
                            "| chat=%s", chat_id, exc_info=True)
        except Exception:          # pragma: no cover — fail-open
            logger.debug("[prompt_release] chat_params cache unavailable",
                         exc_info=True)


# ═══════════════════════════════════════════════════════════════════════════
# Версионированная запись активного текста (правка/откат/вперёд)
# ═══════════════════════════════════════════════════════════════════════════

async def write_versioned_value(block_id: str, text: str, *, cache=None,
                                store=None, scope: str = "global",
                                chat_id: int | None = None, actor=None,
                                reason: str = "",
                                kind: str = "manual_edit") -> dict:
    """Единственная запись активного текста через журнал (контракт §1.6).

    Ревизия (``origin=manual``, идемпотентная) + строка активации + значение
    идут одной транзакцией; ``factory_revision_applied`` НЕ сбрасывается:
    правка «поверх» уже применённой заводской ревизии, рестарт без новой
    метки её не тронет, следующая НОВАЯ метка снимет её в историю.
    Журнал недоступен → ``journal_recorded=False`` (честный признак вместо
    тихой неподмеченной записи; вызывающий решает, как surfaced).
    """
    spec = pr.block(block_id)
    if spec is None or not spec.pg_key:
        return {"applied": False, "reason": "block_not_pg_managed",
                "block_id": block_id}
    store = store if store is not None else default_journal(cache)
    if store is None:
        return {"applied": False, "reason": "journal_unavailable",
                "block_id": block_id, "journal_recorded": False}
    try:
        await store.ensure_journal()
    except Exception:
        logger.warning("[prompt_release] журнал недоступен для правки",
                       exc_info=True)
        return {"applied": False, "reason": "journal_unavailable",
                "block_id": block_id, "journal_recorded": False}
    state = await store.read_applied(spec.block_id, scope, chat_id)
    text = str(text or "")
    async with store.transaction() as tx:
        try:
            revision = await _insert_revision_once(
                store, spec, origin="manual", body=text, scope=scope,
                chat_id=chat_id, actor=str(actor or ""), reason=reason)
            outcome = "applied"
            if scope == "global":
                previous = _spec_current_text(spec, cache)
                if previous == text:
                    outcome = "skipped_same"
                else:
                    await _write_active_value(
                        store, spec, scope, chat_id, text,
                        current_doc=(_spec_current_doc(spec, cache)
                                     if spec.pg_doc_field else None))
            else:
                same = await _read_override_value(store, int(chat_id or 0),
                                                  spec.pg_key)
                if same == text:
                    outcome = "skipped_same"
                else:
                    await _write_active_value(store, spec, scope, chat_id,
                                              text)
            await store.insert_activation(ActivationRow(
                block_id=spec.block_id, scope=scope, chat_id=chat_id,
                revision_id=revision.revision_id,
                factory_revision_applied=(state.factory_revision_applied
                                          if state is not None else ""),
                kind=kind, outcome=outcome, release_id="",
                actor=str(actor or ""), detail_code=reason))
        except Exception:
            logger.error("[prompt_release] ручная запись отменена | "
                         "block=%s | scope=%s", spec.block_id, scope,
                         exc_info=True)
            raise
    if outcome == "applied" and cache is not None and scope == "global":
        try:
            category = "content" if spec.pg_doc_field else "prompts"
            value: object = text
            if spec.pg_doc_field:
                from services.prompt_factory import _doc_from_raw
                raw = cache.get(spec.pg_key, None)
                value = _doc_with_field_public(_doc_from_raw(raw),
                                               spec.pg_doc_field, text)
            await cache.set(spec.pg_key, value, category)
        except Exception:      # pragma: no cover — память не роняет правку
            logger.warning("[prompt_release] кэш памяти не обновлён | "
                           "key=%s", spec.pg_key, exc_info=True)
    if scope == "chat" and chat_id is not None:
        try:
            from services.chat_params import get_chat_params_cache
            chat_cache = get_chat_params_cache()
            if chat_cache is not None:
                await chat_cache.invalidate_chat(int(chat_id))
        except Exception:          # pragma: no cover — fail-open
            pass
    logger.info("[prompt_release] manual edit | block=%s | scope=%s | "
                "chat=%s | sha=%s | outcome=%s | actor=%s", spec.block_id,
                scope, chat_id, revision.content_sha12, outcome,
                str(actor or ""))
    return {"applied": outcome == "applied", "reason": "ok",
            "block_id": spec.block_id, "pg_key": spec.pg_key,
            "scope": scope, "chat_id": chat_id,
            "revision_id": revision.revision_id,
            "sha256_12": revision.content_sha12,
            "factory_revision_applied": (state.factory_revision_applied
                                         if state is not None else ""),
            "outcome": outcome, "journal_recorded": True}


def _doc_with_field_public(document: dict, field_name: str, text: str) -> dict:
    from services.prompt_factory import _doc_with_field
    return _doc_with_field(document, field_name, text, set_level=True)


async def _read_override_value(store, chat_id: int, pg_key: str) -> str | None:
    for chat_id_, value in await store.iter_chat_overrides(pg_key):
        if chat_id_ == chat_id:
            return value
    return None


async def record_manual_activation(block_id: str, text: str, *, scope: str =
                                   "global", chat_id: int | None = None,
                                   actor=None, reason: str = "",
                                   kind: str = "manual_edit", cache=None,
                                   store=None) -> dict:
    """Журналировать факт активации текста БЕЗ повторной записи значения.

    Для путей, у которых запись значения принадлежит своему владельцу
    (per-chat override идёт через ``chat_params.set_chat_params`` со своей
    историей и локами; ``apply_factory_reset``/``restore_backup`` пишут
    глобальный слой штатным API): журнал получает ревизию + строку активации,
    ``factory_revision_applied`` сохраняется. Best-effort: сбой журнала не
    откатывает уже выполненную запись значения (как и прежний провенанс).
    """
    spec = pr.block(block_id)
    if spec is None:
        return {"recorded": False, "reason": "block_unknown"}
    store = store if store is not None else default_journal(cache)
    if store is None:
        return {"recorded": False, "reason": "journal_unavailable"}
    try:
        await store.ensure_journal()
        state = await store.read_applied(spec.block_id, scope, chat_id)
        revision = await _insert_revision_once(
            store, spec, origin="manual", body=str(text or ""), scope=scope,
            chat_id=chat_id, actor=str(actor or ""), reason=reason)
        await store.insert_activation(ActivationRow(
            block_id=spec.block_id, scope=scope, chat_id=chat_id,
            revision_id=revision.revision_id,
            factory_revision_applied=(state.factory_revision_applied
                                      if state is not None else ""),
            kind=kind, outcome="applied", release_id="", actor=str(actor or ""),
            detail_code=reason))
    except Exception:
        # Best-effort (контракт): сбой журнала не роняет уже выполненную
        # запись значения — вызывающий получает честный recorded=False.
        logger.warning("[prompt_release] факт активации не журналирован | "
                       "block=%s | scope=%s", spec.block_id, scope,
                       exc_info=True)
        return {"recorded": False, "reason": "journal_error"}
    logger.info("[prompt_release] manual activation | block=%s | scope=%s | "
                "chat=%s | sha=%s | kind=%s | actor=%s", spec.block_id,
                scope, chat_id, revision.content_sha12, kind,
                str(actor or ""))
    return {"recorded": True, "revision_id": revision.revision_id,
            "sha256_12": revision.content_sha12}


async def activate_revision(block_id: str, revision_id: str, *, scope: str =
                            "global", chat_id: int | None = None,
                            actor=None, cache=None, store=None) -> dict:
    """Откат/вперёд: включить сохранённую совместимую ревизию (EVOL-017 API).

    Гейты: ревизия существует, не ``retired``, ``schema_compat`` совместим
    (пустой = совместим со всем), полномочия (hook). Несовместимая ревизия
    НЕ включается: ``applied=false, reason=schema_incompatible``, активный
    указатель не меняется, прежняя активная остаётся. История не удаляется;
    ``factory_revision_applied`` сохраняется — следующая НОВАЯ метка снова
    включает заводской текст (контракт §1.4).
    """
    spec = pr.block(block_id)
    if spec is None or not spec.pg_key:
        return {"applied": False, "reason": "block_not_pg_managed",
                "block_id": block_id}
    check_permission(str(actor or ""), "prompt.activate", block_id=block_id,
                     scope=scope, chat_id=chat_id)
    store = store if store is not None else default_journal(cache)
    if store is None:
        return {"applied": False, "reason": "journal_unavailable",
                "block_id": block_id}
    try:
        await store.ensure_journal()
    except Exception:
        return {"applied": False, "reason": "journal_unavailable",
                "block_id": block_id}
    revision = await store.get_revision(revision_id)
    if revision is None or revision.block_id != spec.block_id:
        return {"applied": False, "reason": "revision_unknown",
                "block_id": block_id, "revision_id": revision_id}
    if revision.retired:
        return {"applied": False, "reason": "revision_retired",
                "block_id": block_id, "revision_id": revision_id}
    if revision.schema_compat and revision.schema_compat not in \
            SUPPORTED_SCHEMA_COMPAT:
        logger.warning("[prompt_release] schema_incompatible на попытке "
                       "включения | block=%s | revision=%s | schema=%s",
                       spec.block_id, revision_id, revision.schema_compat)
        return {"applied": False, "reason": "schema_incompatible",
                "block_id": block_id, "revision_id": revision_id,
                "schema_compat": revision.schema_compat}
    state = await store.read_applied(spec.block_id, scope, chat_id)
    kind = "manual_rollback"
    if state is not None and state.revision_id and \
            state.revision_id != revision_id:
        # Детерминированный порядок (вставка ревизий в журнал), не часы:
        # цель создана раньше активной → откат; позже или порядок неизвестен
        # → возврат вперёд (EVOL-017: «выбор сохранённого состояния»).
        precedes = await store.revision_precedes(revision_id,
                                                 state.revision_id)
        kind = "manual_rollback" if precedes else "manual_forward"
    # Ревью F2: активация указывает на ЗАПРОШЕННУЮ ревизию — клона origin=manual
    # не создаётся; байты записываются, origin сохраняется у самой ревизии
    # (rollback на manual-правку остаётся manual, forward на заводскую —
    # factory); ``factory_revision_applied`` не сбрасывается.
    async with store.transaction() as tx:
        try:
            outcome = "applied"
            if scope == "global":
                previous = _spec_current_text(spec, cache)
                if previous == revision.body:
                    outcome = "skipped_same"
                else:
                    await _write_active_value(
                        store, spec, scope, chat_id, revision.body,
                        current_doc=(_spec_current_doc(spec, cache)
                                     if spec.pg_doc_field else None))
            else:
                same = await _read_override_value(store, int(chat_id or 0),
                                                  spec.pg_key)
                if same == revision.body:
                    outcome = "skipped_same"
                else:
                    await _write_active_value(store, spec, scope, chat_id,
                                              revision.body)
            await store.insert_activation(ActivationRow(
                block_id=spec.block_id, scope=scope, chat_id=chat_id,
                revision_id=revision.revision_id,
                factory_revision_applied=(state.factory_revision_applied
                                          if state is not None else ""),
                kind=kind, outcome=outcome, release_id="",
                actor=str(actor or ""),
                detail_code=f"activate:{revision.origin}"))
        except Exception:
            logger.error("[prompt_release] активация ревизии отменена | "
                         "block=%s | revision=%s", spec.block_id,
                         revision_id, exc_info=True)
            raise
    if outcome == "applied" and cache is not None and scope == "global":
        try:
            category = "content" if spec.pg_doc_field else "prompts"
            value: object = revision.body
            if spec.pg_doc_field:
                from services.prompt_factory import _doc_from_raw
                raw = cache.get(spec.pg_key, None)
                value = _doc_with_field_public(_doc_from_raw(raw),
                                               spec.pg_doc_field,
                                               revision.body)
            await cache.set(spec.pg_key, value, category)
        except Exception:      # pragma: no cover — память не роняет активацию
            logger.warning("[prompt_release] кэш памяти не обновлён | "
                           "key=%s", spec.pg_key, exc_info=True)
    if scope == "chat" and chat_id is not None:
        try:
            from services.chat_params import get_chat_params_cache
            chat_cache = get_chat_params_cache()
            if chat_cache is not None:
                await chat_cache.invalidate_chat(int(chat_id))
        except Exception:          # pragma: no cover — fail-open
            pass
    logger.info("[prompt_release] revision activated | block=%s | scope=%s | "
                "chat=%s | rev=%s | origin=%s | kind=%s | outcome=%s | "
                "actor=%s", spec.block_id, scope, chat_id,
                revision.revision_id, revision.origin, kind, outcome,
                str(actor or ""))
    return {"applied": outcome == "applied", "reason": "ok",
            "block_id": spec.block_id, "pg_key": spec.pg_key,
            "scope": scope, "chat_id": chat_id,
            "revision_id": revision.revision_id,
            "sha256_12": revision.content_sha12,
            "factory_revision_applied": (state.factory_revision_applied
                                         if state is not None else ""),
            "outcome": outcome, "journal_recorded": True,
            "activated_revision": revision_id,
            "activated_origin": revision.origin,
            "activation_kind": kind}


async def list_versions(block_id: str, *, scope: str = "global",
                        chat_id: int | None = None, cache=None,
                        store=None, actor=None) -> dict:
    """Данные «Истории версий» (EVOL-017): активная ревизия, заводская,
    хронология ревизий и событий включения. Тексты по умолчанию не отдаются
    (источник просмотра — ``get_revision_source``/``diff_revisions``).
    Ревью F4: доступ через hook полномочий (checker, иначе непустой actor)."""
    spec = pr.block(block_id)
    if spec is None:
        return {"block_id": block_id, "known": False}
    check_permission(str(actor or ""), "prompt.list_versions",
                     block_id=block_id, scope=scope, chat_id=chat_id)
    store = store if store is not None else default_journal(cache)
    revisions: list = []
    activations: list = []
    state = None
    if store is not None:
        try:
            await store.ensure_journal()
            revisions = await store.list_revisions(block_id, chat_id)
            activations = await store.list_activations(block_id, chat_id)
            state = await store.read_applied(spec.block_id, scope, chat_id)
        except Exception:      # pragma: no cover — журнал не роняет view
            logger.warning("[prompt_release] список ревизий недоступен",
                           exc_info=True)
    active = None
    if state is not None and state.revision_id:
        rev = await store.get_revision(state.revision_id)
        if rev is not None:
            active = {"revision_id": rev.revision_id, "origin": rev.origin,
                      "sha256_12": rev.content_sha12,
                      "chars": len(rev.body), "created_at": rev.created_at,
                      "factory_revision_applied":
                          state.factory_revision_applied}
    return {
        "block_id": spec.block_id,
        "pg_key": spec.pg_key or "",
        "known": True,
        "factory_revision": pr.factory_revision(block_id),
        "sealed_revision": pr.sealed_factory_revision(block_id),
        "factory_matches_active": bool(
            active and active["sha256_12"] == pr.sha12(
                pr.factory_text(block_id))),
        "active": active,
        "revisions": [{
            "revision_id": r.revision_id, "origin": r.origin,
            "sha256_12": r.content_sha12, "chars": _revision_chars(store, r),
            "factory_revision": r.factory_revision,
            "release_id": r.release_id, "actor": r.actor, "reason": r.reason,
            "retired": r.retired, "created_at": r.created_at,
            "schema_compat": r.schema_compat,
        } for r in revisions],
        "activations": [{
            "kind": a.kind, "outcome": a.outcome,
            "revision_id": a.revision_id, "scope": a.scope,
            "chat_id": a.chat_id, "release_id": a.release_id,
            "actor": a.actor, "detail_code": a.detail_code,
        } for a in activations],
    }


def _revision_chars(store, revision: RevisionRow) -> int:
    if revision.body:
        return len(revision.body)
    full = None
    try:
        full = store.get_revision(revision.revision_id)
    except Exception:          # pragma: no cover
        full = None
    return len(full.body) if full is not None else 0


async def get_revision_source(revision_id: str, *, cache=None,
                              store=None, actor=None) -> dict:
    """Полный текст ревизии (просмотр/diff-источник в EVOL-017).
    Ревью F4: доступ через hook полномочий; тела промптов в логи не пишутся."""
    check_permission(str(actor or ""), "prompt.get_revision_source",
                     revision_id=revision_id)
    store = store if store is not None else default_journal(cache)
    if store is None:
        return {"known": False, "reason": "journal_unavailable",
                "revision_id": revision_id}
    revision = await store.get_revision(revision_id)
    if revision is None:
        return {"known": False, "reason": "revision_unknown",
                "revision_id": revision_id}
    return {"known": True, "revision_id": revision.revision_id,
            "block_id": revision.block_id, "origin": revision.origin,
            "sha256_12": revision.content_sha12, "body": revision.body,
            "created_at": revision.created_at, "retired": revision.retired,
            "schema_compat": revision.schema_compat}


async def diff_revisions(revision_a: str, revision_b: str, *, cache=None,
                         store=None, actor=None) -> dict:
    """Сравнение двух ревизий (существующий ``difflib``, не новый движок).
    Ревью F4: доступ через hook полномочий."""
    check_permission(str(actor or ""), "prompt.diff_revisions",
                     revision_a=revision_a, revision_b=revision_b)
    a = await get_revision_source(revision_a, cache=cache, store=store,
                                  actor=actor)
    b = await get_revision_source(revision_b, cache=cache, store=store,
                                  actor=actor)
    if not a.get("known") or not b.get("known"):
        return {"known": False,
                "reason": a.get("reason") or b.get("reason") or "unknown"}
    diff = list(difflib.unified_diff(
        (a["body"] or "").splitlines(), (b["body"] or "").splitlines(),
        fromfile=revision_a, tofile=revision_b, lineterm=""))
    return {"known": True, "diff": diff,
            "added_lines": sum(1 for x in diff if x.startswith("+")
                               and not x.startswith("+++")),
            "removed_lines": sum(1 for x in diff if x.startswith("-")
                                 and not x.startswith("---"))}


__all__ = [
    "CUTOVER_RELEASE_ID", "JOURNAL_DDL", "SUPPORTED_SCHEMA_COMPAT",
    "RevisionRow", "ActivationRow", "AppliedState", "BlockReleaseResult",
    "JournalUnavailable", "PromptJournalError", "PromptPermissionError",
    "PermissionChecker", "set_permission_checker", "check_permission",
    "MemoryPromptJournal", "PgPromptJournal", "default_journal",
    "apply_release", "write_versioned_value", "record_manual_activation",
    "activate_revision", "list_versions", "get_revision_source",
    "diff_revisions",
]
