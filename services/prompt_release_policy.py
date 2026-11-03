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
  * ``write_versioned_value`` — тонкая обёртка над ``write_prompt_values``
    (совместимость вызовов и тестов);
  * ``write_prompt_values`` — ЕДИНСТВЕННАЯ запись значения промпта
    (ревизия + событие активации + значение одной PG-транзакцией под
    ``APPLY_LOCK_SQL``; ``SET LOCAL lock_timeout='5s'``);
  * ``remove_prompt_override`` — снятие чатового override со снимком текста;
  * ``capture_pre_versioning_values`` — первый захват уже действующих
    ручных байтов (``origin=legacy``, ``reason=pre_versioning_import``);
  * рантайм-страж обхода ``PromptJournalBypass``: ``ConfigCache.set/set_many``
    и ``chat_params.set_chat_params`` отказывают, если текст промпта пишется
    без журнального токена (``journal_write_scope``);
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
import contextlib
import contextvars
import datetime
import difflib
import json
import logging
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

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
_SELECT_SETTING_UPDATED_AT_SQL = (
    "SELECT updated_at FROM bot_settings WHERE key = $1")
#: Таймаут ожидания advisory-лока транзакции записи (контракт §2.3/§3.3):
#: занятый лок → честный отказ (503), а не бесконечное ожидание в UI.
LOCK_TIMEOUT_SQL = "SET LOCAL lock_timeout = '5s'"
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
  AND kind = 'legacy_import'
  AND detail_code IN ('legacy_snapshot', 'legacy_empty') LIMIT 1
"""
_GET_REVISION_SQL = (
    "SELECT revision_id, block_id, pg_key, scope, chat_id, origin, "
    "content_sha12, body, factory_revision, schema_compat, release_id, "
    "actor, reason, source_updated_at, retired, created_at "
    "FROM prompt_revisions WHERE revision_id = $1")
_LIST_REVISIONS_SQL = """
SELECT revision_id, block_id, pg_key, scope, chat_id, origin, content_sha12,
       factory_revision, schema_compat, release_id, actor, reason,
       source_updated_at, retired, created_at, length(body) AS char_count
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
    #: Длина текста ревизии в символах (без загрузки самого тела).
    #: ``None`` — стор не сообщил длину; тогда считается по ``body``.
    chars: int | None = None


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
    #: Время события включения (аудит). Пустая строка — стор времени не дал.
    created_at: str = ""


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


def _row_matches_chat(row, chat_id: int | None) -> bool:
    """Фильтр строки журнала по адресату — та же семантика, что SQL PG-стора.

    ``PG`` отбирает ``chat_id = $2 OR (chat_id IS NULL AND $2 IS NULL)``;
    фильтр по ``scope`` в SQL не участвует (иначе история чата пустела бы при
    ``scope='global'`` по умолчанию). Двойник обязан вести себя так же.
    """
    if chat_id is None:
        return row.chat_id is None
    return row.chat_id is not None and int(row.chat_id) == int(chat_id)


# ═══════════════════════════════════════════════════════════════════════════
# Ошибки и hook полномочий
# ═══════════════════════════════════════════════════════════════════════════

class JournalUnavailable(RuntimeError):
    """Журнал недоступен (PG down / пул отсутствует) — честный no-op."""


class PromptJournalError(RuntimeError):
    """Ошибка проводки релиза (срыв пакета: ни один ключ не изменён)."""


class PromptPermissionError(PermissionError):
    """Отказ проверки полномочий на операцию с ревизиями (EVOL-017 hook)."""


class PromptJournalBypass(RuntimeError):
    """Текст промпта пишется в обход журнала версий (EPIC-PROMPT-VERSIONING-UX-01).

    Поднимается ``ConfigCache.set``/``set_many`` и
    ``chat_params.set_chat_params``, когда значение блока реестра пишется без
    журнального токена, то есть без ревизии и события активации. Запись при
    этом НЕ выполняется: обход невозможен, а не «будет замечен позже в
    истории».
    """


#: Ключи реестра, чьё значение — НЕ текст промпта, а слот выбора (профиль
#: обложки). Такие значения не создают ревизию текста и не подпадают под
#: страж обхода: писать их вправе владелец выбора стиля (POST /api/cover/select).
NON_TEXT_VALUE_KEYS: frozenset[str] = frozenset({
    "prompts.summary_cover_style_id",
})


@dataclass(frozen=True)
class JournalWriteGrant:
    """Право записи значения одного блока в одном scope внутри транзакции."""

    block_id: str
    scope: str
    chat_id: int | None = None


#: Токен «эта запись идёт через журнал». Ставится ТОЛЬКО журнальными
#: писателями (``write_prompt_values``/``remove_prompt_override``/
#: ``activate_revision``/``apply_release``) и только на время их работы.
_journal_write_token: contextvars.ContextVar[
    tuple[JournalWriteGrant, ...] | None] = contextvars.ContextVar(
        "prompt_journal_write_token", default=None)

#: Узкая декларация код-поставленной миграции текста (НЕ правка владельца):
#: значение приходит из кода, миграция обязана вести собственный неизменяемый
#: снимок и откат. Каждое использование пишется в лог с id миграции.
_legacy_migration_token: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "prompt_legacy_migration", default=None)


@contextlib.contextmanager
def journal_write_scope(grants: Iterable[JournalWriteGrant]):
    """Разрешить запись перечисленных (block, scope, chat) на время блока."""
    token = _journal_write_token.set(tuple(grants))
    try:
        yield
    finally:
        _journal_write_token.reset(token)


@contextlib.contextmanager
def legacy_migration_write(migration_id: str, *, keys: Iterable[str] = ()):
    """Разрешить запись текста код-поставленной миграцией (явно и с логом).

    Применяется только утилитами переноса/нормализации канонов, которые ведут
    собственную неизменяемую запись и откат (``services/prompt_migrations``).
    Это НЕ путь правки владельца и НЕ путь API: значения приходят из кода.
    """
    logger.warning("[prompt_release] legacy migration write | id=%s | keys=%s",
                   migration_id, sorted(str(k) for k in keys))
    token = _legacy_migration_token.set(str(migration_id))
    try:
        yield
    finally:
        _legacy_migration_token.reset(token)


def journal_write_granted(block_id: str, scope: str,
                          chat_id: int | None = None) -> bool:
    """Есть ли действующее право журнальной записи для (block, scope, chat)."""
    grants = _journal_write_token.get()
    if not grants:
        return False
    return JournalWriteGrant(str(block_id), str(scope), chat_id) in grants


def _as_doc(raw) -> dict:
    """JSON-документ из значения слоя (``{}``, если документа нет)."""
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            parsed = json.loads(raw.decode("utf-8") if isinstance(
                raw, (bytes, bytearray)) else raw)
        except Exception:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _block_text_value(spec, raw) -> str | None:
    """Текст значения блока из значения слоя (``None`` — значения нет)."""
    if raw is None:
        return None
    field_name = getattr(spec, "pg_doc_field", "") or ""
    if field_name:
        return pr.doc_field_text(_as_doc(raw), field_name)
    return str(raw)


#: Блоки реестра по общему ``pg_key`` (один документ = несколько блоков-полей,
#: например ``character.core`` → ``core.personality`` / ``.compact``).
#: Объявления реестра статичны, поэтому таблица строится один раз.
_blocks_by_pg_key: dict[str, tuple] = {}


def _blocks_for_pg_key(pg_key: str) -> tuple:
    key = str(pg_key)
    cached = _blocks_by_pg_key.get(key)
    if cached is not None:
        return cached
    blocks = tuple(spec for spec in pr.all_blocks() if spec.pg_key == key)
    _blocks_by_pg_key[key] = blocks
    return blocks


def assert_prompt_write_allowed(*, pg_key: str, scope: str,
                                chat_id: int | None = None,
                                current=None, new=None) -> None:
    """Страж обхода: запретить запись текста промпта без журнального токена.

    Пропускается:
      * ключ вне реестра промптов / без ``pg_key``;
      * ключ из :data:`NON_TEXT_VALUE_KEYS` (значение — слот выбора);
      * блок-ПОЛЕ документа (Personality Core), у которого текст НИ ОДНОГО
        поля не меняется (``POST /api/speech/core/meta`` правит только
        ``detail_level``/``enabled``). Одно ``pg_key`` может нести несколько
        блоков-полей — проверяются все.
    """
    spec = pr.by_pg_key(str(pg_key))
    if spec is None or not spec.pg_key:
        return
    if str(pg_key) in NON_TEXT_VALUE_KEYS:
        return
    if getattr(spec, "pg_doc_field", ""):
        changed = [block for block in _blocks_for_pg_key(spec.pg_key)
                   if (_block_text_value(block, current) or "")
                   != (_block_text_value(block, new) or "")]
        if not changed:
            return                   # правка метаданных документа, не текста
        if any(journal_write_granted(block.block_id, scope, chat_id)
               for block in changed):
            return
    elif journal_write_granted(spec.block_id, scope, chat_id):
        return
    if _legacy_migration_token.get():
        return
    logger.error("[prompt_release] journal bypass blocked | block=%s | "
                 "scope=%s | chat=%s | key=%s", spec.block_id, scope, chat_id,
                 spec.pg_key)
    raise PromptJournalBypass(
        f"{spec.pg_key}: запись текста промпта без журнала версий запрещена "
        f"(block={spec.block_id}, scope={scope}, chat={chat_id})")


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
        #: Токены ``bot_settings.updated_at`` для проверки CAS в тестах
        #: (в PG стор отдаёт их из хранилища).
        self.settings_updated_at: dict[str, str] = {}

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
                   and row.detail_code in ("legacy_snapshot", "legacy_empty")
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
        rows = [RevisionRow(**{**vars(r), "chars": len(r.body or "")})
                for r in self.revisions.values()
                if r.block_id == block_id
                and _row_matches_chat(r, chat_id)
                and (include_retired or not r.retired)]
        rows.sort(key=lambda r: (r.created_at, r.revision_id))
        return rows

    async def list_activations(self, block_id: str,
                               chat_id: int | None = None,
                               limit: int = 50,
                               scope: str = "global") -> list[ActivationRow]:
        rows = [ActivationRow(**vars(a)) for a in self.activations
                if a.block_id == block_id
                and _row_matches_chat(a, chat_id)]
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
        if not row.created_at:
            row.created_at = _utc_now()
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

    # — профиль чата (overrides/meta): источник для единого слоя записи —
    async def read_updated_at(self, pg_key: str) -> str | None:
        """Optimistic-токен глобального ключа.

        У in-memory стора токенов нет (пустой словарь): CAS проверяется только
        там, где ``bot_settings.updated_at`` реально существует. Тест может
        задать токен явно (``settings_updated_at``), чтобы проверить 409.
        """
        return self.settings_updated_at.get(str(pg_key))

    async def read_chat_state(self, chat_id: int, *, pg=None) -> dict | None:
        if pg is not None:                  # тестовый двойник PG: профиль там
            return await _read_chat_state_from_pg(pg, int(chat_id))
        # Процесс-глобальный слой чат-параметров — тот же, что читает резолвер:
        # двойник обязан писать туда, откуда читают тесты (как PG-стор).
        root = await _chat_cache_call("get_chat_params", int(chat_id))
        if isinstance(root, dict):
            return {"overrides": dict(root.get("overrides") or {}),
                    "meta": dict(root.get("meta") or {}),
                    "updated_at": root.get("updated_at")}
        return {"overrides": dict(self._live.chat_overrides.get(int(chat_id))
                                  or {}),
                "meta": {}, "updated_at": None}

    async def write_chat_state(self, chat_id: int, overrides: dict,
                               meta: dict, *, expected_updated_at: str | None =
                               None, changed_by=None, pg=None) -> str | None:
        if pg is not None:
            from services import chat_params
            result = await chat_params.set_chat_params(
                int(chat_id), {"overrides": dict(overrides),
                               "meta": dict(meta or {})},
                changed_by=changed_by, expected_updated_at=expected_updated_at,
                pg=pg)
            return getattr(result, "updated_at", None)
        written = await _chat_cache_call(
            "set_chat_params", int(chat_id),
            {"overrides": dict(overrides), "meta": dict(meta or {})},
            changed_by=changed_by, expected_updated_at=expected_updated_at)
        if written is not None:
            return getattr(written, "updated_at", None)
        self._live.chat_overrides[int(chat_id)] = dict(overrides)
        await self.notify_chat(int(chat_id))
        return None


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
                # Ограничение ожидания лока: занятый advisory-лок → отказ
                # (честный 503), а не бесконечное ожидание в UI (§2.3/§3.3).
                await self.conn.execute(LOCK_TIMEOUT_SQL)
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
                created_at=str(row["created_at"]),
                chars=int(row["char_count"] or 0)))
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
            actor=r["actor"] or "", detail_code=r["detail_code"] or "",
            created_at=str(r["created_at"] or ""))
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

    async def read_updated_at(self, pg_key: str) -> str | None:
        """``bot_settings.updated_at`` — optimistic-токен глобального ключа."""
        async def _run(conn):
            return await conn.fetchval(_SELECT_SETTING_UPDATED_AT_SQL, pg_key)
        value = await self._run_on_conn(_run)
        return None if value is None else str(value)

    async def read_chat_state(self, chat_id: int, *, pg=None) -> dict | None:
        """Текущий профиль чата (overrides/meta/updated_at) в той же транзакции."""
        from services import chat_params

        async def _run(conn):
            row = await conn.fetchrow(chat_params.SELECT_PROFILE_SQL,
                                      int(chat_id))
            return None if row is None else _chat_state_from_row(row)
        return await self._run_on_conn(_run)

    async def write_chat_state(self, chat_id: int, overrides: dict,
                               meta: dict, *, expected_updated_at: str | None =
                               None, changed_by=None, pg=None) -> str | None:
        """Записать набор overrides ТЕМ ЖЕ ``set_chat_params`` на tx-коннекте.

        Сохраняются CAS-токен (``expected_updated_at``), ``chat_params_history``,
        ``meta.updated_by`` и NOTIFY: значение не пишется «своим» SQL в обход
        оптимистичного протокола.
        """
        from services import chat_params
        if self._tx_conn is None:       # pragma: no cover — контракт транзакции
            raise PromptJournalError(
                "write_chat_state outside journal transaction")
        result = await chat_params.set_chat_params(
            int(chat_id),
            {"overrides": dict(overrides), "meta": dict(meta or {})},
            changed_by=changed_by, expected_updated_at=expected_updated_at,
            conn=self._tx_conn)
        return getattr(result, "updated_at", None)


async def _chat_cache_call(method: str, *args, **kwargs):
    """Вызвать метод процесс-глобального чат-кэша (если он его реализует).

    Тестовые двойники чат-слоя подменяют ``chat_params._chat_params_cache``;
    in-memory стор журнала пишет туда же, откуда читает резолвер (как PG-стор).
    ``None`` — метод не реализован (или кэш не установлен).
    """
    from services import chat_params
    cache = chat_params.get_chat_params_cache()
    fn = getattr(cache, method, None) if cache is not None else None
    if fn is None:
        return None
    result = fn(*args, **kwargs)
    if hasattr(result, "__await__"):
        result = await result
    return result


async def _read_chat_state_from_pg(pg, chat_id: int) -> dict | None:
    """Профиль чата из PG-пула (для стора-двойника и вне транзакции).

    SQL/парсинг — те же, что у ``chat_params`` (одна форма профиля, двойники
    тестов продолжают работать без второго диалекта).
    """
    from services import chat_params
    pool = getattr(pg, "pool", None)
    if pool is None:
        raise JournalUnavailable("PostgreSQL недоступен (пул отсутствует)")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(chat_params.SELECT_PROFILE_SQL, int(chat_id))
    return _chat_state_from_row(row) if row is not None else None


def _chat_state_from_row(row) -> dict:
    """``{overrides, meta, updated_at}`` из строки ``chat_profiles``."""
    from services import chat_params
    raw = chat_params._load_chat_params(row["chat_params"])
    return {"overrides": dict(raw.get("overrides") or {}),
            "meta": dict(raw.get("meta") or {}),
            "updated_at": chat_params._iso(row["updated_at"])}


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
    captured = 0
    async with store.apply_lock():
        async with store.transaction() as tx:
            try:
                orphans = await _import_provenance_history(store, cache=cache)
                # §3.7: первый захват уже действующих ручных байтов (в т.ч.
                # мемных промптов, введённых после применения метки) — до
                # первой версионированной записи и без активации.
                captured = await capture_pre_versioning_values(store,
                                                               cache=cache)
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
            "orphan_history_blocks": sorted(orphans),
            "captured_pre_versioning": captured}


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
                              doc_state: dict[str, dict] | None = None,
                              set_level: bool = False,
                              base_doc: dict | None = None
                              ) -> None:
    """Записать активное значение в той же транзакции (нет второго источника)."""
    doc_state = doc_state if doc_state is not None else {}
    if scope == "chat":
        await store.set_chat_override(int(chat_id), spec.pg_key, value)
        await store.notify_chat(int(chat_id))
        return
    if spec.pg_doc_field:
        # Поле документа Core: read-modify-write в транзакции; второе поле
        # цело; выбор detail_level владельца не меняется (set_level=False).
        # База документа: явная (``base_doc``), запись этой же транзакции
        # (doc_state) → текущий документ слоя (кэш) → документ стора.
        from services.prompt_factory import _doc_from_raw, _doc_with_field
        if base_doc is not None:
            doc = dict(base_doc)
        elif current_doc is not None:
            doc = dict(current_doc)
        else:
            raw = await store.read_global(spec.pg_key)
            doc = _doc_from_raw(raw)
        doc = _doc_with_field(doc, spec.pg_doc_field, value,
                              set_level=set_level)
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
            spec_block = pr.by_pg_key(pg_key)
            grants = ([JournalWriteGrant(spec_block.block_id, "global", None)]
                      if spec_block is not None else [])
            # Синхронизация памяти — часть уже закоммиченной журнальной
            # записи: токен выдаётся этому же писателю, страж обхода не
            # мешает законному обновлению кэша (§3.2 п.9).
            with journal_write_scope(grants):
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

# ═══════════════════════════════════════════════════════════════════════════
# Единый атомарный слой записи (контракт §3)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class PromptWriteItem:
    """Одно значение промпта в пакете записи (контракт §3.1)."""

    block_id: str                  # block_id реестра (или pg_key — резолв)
    text: str
    #: CAS-токен вызывающего: ``bot_settings.updated_at`` (global) /
    #: ``chat_profiles.updated_at`` (chat). ``None`` — проверка не требуется.
    expected_updated_at: str | None = None
    #: Правка поля документа Core делает редакцию действующей (как в
    #: ``prompt_factory._doc_with_field``); миграции передают False.
    set_level: bool = True


def _is_lock_timeout(exc: BaseException) -> bool:
    """Похоже ли исключение на отказ по таймауту блокировки."""
    name = type(exc).__name__.lower()
    return ("locknotavailable" in name or "querycanceled" in name
            or "timeout" in name)


def _reject(key: str, reason: str) -> dict:
    return {"key": key, "reason": reason}


async def write_prompt_values(items: Sequence[PromptWriteItem], *,
                              scope: str = "global",
                              chat_id: int | None = None, cache=None, store=None,
                              pg=None, actor=None, reason: str = "",
                              kind: str = "manual_edit",
                              origin: str = "manual") -> dict:
    """ЕДИНСТВЕННАЯ запись значения промпта (контракт §3.1–§3.5).

    Ревизия (идемпотентная по ``revision_id``), строка активации и само
    значение пишутся ОДНОЙ PG-транзакцией под тем же advisory-локом, что и
    релизная поставка (``APPLY_LOCK_SQL``), с ``SET LOCAL lock_timeout='5s'``.
    Все решения (``skipped_same``, ``read_applied``, полный набор overrides
    чата) читаются ВНУТРИ транзакции на её коннекте — не из памяти кэша.

    Отказы (заморожены §3.3): журнал недоступен или лок занят →
    :class:`JournalUnavailable` (HTTP 503), значение НЕ записано; CAS-конфликт
    ``chat_params`` → :class:`services.chat_params.ChatParamsConflict` (409);
    устаревший global-токен → ``prompt_factory.FactoryConflict`` (409);
    гейты значения → ``rejected`` (422 у вызывающего). Возврата
    ``journal_recorded=False`` как успеха больше нет.

    Возврат — замороженная форма §3.1: ``applied``, ``skipped_same``,
    ``rejected``, ``prompt_snapshots``, ``chat_updated_at``,
    ``journal_recorded``.
    """
    scope = str(scope or "global")
    if scope not in ("global", "chat"):
        raise ValueError(f"неизвестный scope: {scope}")
    if scope == "chat" and chat_id is None:
        raise ValueError("scope=chat требует chat_id")

    resolved: list[tuple] = []
    rejected: list[dict] = []
    for item in items:
        spec = pr.block(item.block_id) or pr.by_pg_key(item.block_id)
        if spec is None:
            rejected.append(_reject(str(item.block_id), "block_unknown"))
            continue
        if not spec.pg_key:
            rejected.append(_reject(spec.block_id, "block_not_pg_managed"))
            continue
        text = str(item.text if item.text is not None else "")
        if not text.strip():
            rejected.append(_reject(spec.pg_key, "empty_value"))
            continue
        classification = pr.withheld_classification(spec.block_id, text)
        if classification and classification.get("class") == \
                pr.WITHHELD_LEGACY_CLASS:
            rejected.append({"key": spec.pg_key, "reason": "legacy_incompatible",
                             "detail": classification.get("reason", "")})
            continue
        meme_reason = _meme_template_violation(spec, text)
        if meme_reason:
            rejected.append({"key": spec.pg_key, "reason": "meme_template",
                             "detail": meme_reason})
            continue
        resolved.append((spec, item))

    result = {"applied": [], "skipped_same": [], "rejected": rejected,
              "prompt_snapshots": [], "chat_updated_at": None,
              "journal_recorded": False}
    if not resolved:
        return result               # ни одно значение не пишется

    store = store if store is not None else default_journal(cache)
    if store is None:
        raise JournalUnavailable(
            "журнал версий недоступен: значения промптов не записаны")
    try:
        await store.ensure_journal()
    except Exception as exc:
        raise JournalUnavailable(
            f"журнал версий недоступен: {type(exc).__name__}") from exc

    grants = [JournalWriteGrant(spec.block_id, scope, chat_id)
              for spec, _item in resolved]
    expected_token = next((it.expected_updated_at for _s, it in resolved
                           if it.expected_updated_at is not None), None)
    doc_state: dict[str, dict] = {}
    applied: list[str] = []
    skipped: list[str] = []
    snapshots: list[dict] = []
    written: list[tuple] = []
    chat_updated_at: str | None = None

    with journal_write_scope(grants):
        try:
            async with store.apply_lock():
                async with store.transaction():
                    chat_overrides: dict = {}
                    chat_meta: dict = {}
                    if scope == "chat":
                        state_row = await store.read_chat_state(
                            int(chat_id), pg=pg)
                        if state_row is None:
                            from services import chat_params
                            raise chat_params.ChatParamsConflict(
                                int(chat_id), None)
                        chat_overrides = dict(state_row.get("overrides") or {})
                        chat_meta = dict(state_row.get("meta") or {})
                        chat_meta["updated_by"] = actor
                    for spec, item in resolved:
                        text = str(item.text)
                        base_doc: dict | None = None
                        current_text: str | None = None
                        if scope == "chat":
                            raw = chat_overrides.get(spec.pg_key)
                            if spec.pg_doc_field:
                                own = _as_doc(raw)
                                base_doc = own or _as_doc(
                                    await store.read_global(spec.pg_key))
                                current_text = pr.doc_field_text(
                                    base_doc, spec.pg_doc_field)
                            else:
                                current_text = (None if raw is None
                                                else str(raw))
                        elif spec.pg_doc_field:
                            base_doc = doc_state.get(spec.pg_key)
                            if base_doc is None:
                                base_doc = _as_doc(
                                    await store.read_global(spec.pg_key))
                                doc_state[spec.pg_key] = dict(base_doc)
                            current_text = pr.doc_field_text(
                                base_doc, spec.pg_doc_field)
                        else:
                            raw = await store.read_global(spec.pg_key)
                            current_text = (None if raw is None else str(raw))
                        if item.expected_updated_at is not None and \
                                scope == "global":
                            actual = await store.read_updated_at(spec.pg_key)
                            if actual is not None and \
                                    actual != item.expected_updated_at:
                                from services.prompt_factory import (
                                    FactoryConflict,
                                )
                                raise FactoryConflict(
                                    spec.pg_key, item.expected_updated_at,
                                    actual)
                        state = await store.read_applied(
                            spec.block_id, scope, chat_id)
                        revision = await _insert_revision_once(
                            store, spec, origin=origin, body=text, scope=scope,
                            chat_id=chat_id, actor=str(actor or ""),
                            reason=reason)
                        same = current_text is not None and current_text == text
                        outcome = "skipped_same" if same else "applied"
                        if not same:
                            if scope == "chat":
                                if spec.pg_doc_field:
                                    from services.prompt_factory import (
                                        _doc_with_field,
                                    )
                                    chat_overrides[spec.pg_key] = _doc_with_field(
                                        base_doc or {}, spec.pg_doc_field,
                                        text, set_level=item.set_level)
                                else:
                                    chat_overrides[spec.pg_key] = text
                            else:
                                await _write_active_value(
                                    store, spec, "global", None, text,
                                    base_doc=(base_doc if spec.pg_doc_field
                                              else None),
                                    doc_state=doc_state,
                                    set_level=item.set_level)
                        await store.insert_activation(ActivationRow(
                            block_id=spec.block_id, scope=scope,
                            chat_id=chat_id,
                            revision_id=revision.revision_id,
                            factory_revision_applied=(
                                state.factory_revision_applied
                                if state is not None else ""),
                            kind=kind, outcome=outcome, release_id="",
                            actor=str(actor or ""), detail_code=reason))
                        snapshots.append({
                            "key": spec.pg_key,
                            "revision_id": revision.revision_id,
                            "sha256_12": revision.content_sha12,
                        })
                        if same:
                            skipped.append(spec.pg_key)
                        else:
                            applied.append(spec.pg_key)
                            written.append((spec, text,
                                            doc_state.get(spec.pg_key)))
                    if scope == "chat" and applied:
                        # §3.2 п.7: ОДНА запись полного набора overrides тем же
                        # ``set_chat_params`` на коннекте транзакции — CAS-токен,
                        # история, meta.updated_by и NOTIFY сохраняются.
                        chat_updated_at = await store.write_chat_state(
                            int(chat_id), chat_overrides, chat_meta,
                            expected_updated_at=expected_token,
                            changed_by=actor, pg=pg)
        except PromptJournalBypass:
            raise
        except JournalUnavailable:
            raise
        except Exception as exc:
            from services import chat_params
            from services.prompt_factory import FactoryConflict
            if isinstance(exc, (chat_params.ChatParamsConflict,
                                FactoryConflict)):
                raise
            if _is_lock_timeout(exc):
                logger.warning("[prompt_release] лок журнала занят — запись "
                               "отклонена (lock_timeout)")
                raise JournalUnavailable("lock_timeout") from exc
            logger.error("[prompt_release] запись промптов отменена | "
                         "scope=%s | chat=%s", scope, chat_id, exc_info=True)
            raise

        # §3.2 п.9: только ПОСЛЕ commit — память кэша и чат-кэши. Сбой
        # синхронизации логируется и не превращает commit в «не сохранено».
        for spec, text, doc in written:
            if scope != "global" or cache is None:
                continue
            try:
                if spec.pg_doc_field:
                    await cache.set(spec.pg_key, doc or {}, "content")
                else:
                    await cache.set(spec.pg_key, text, "prompts")
            except Exception:      # pragma: no cover — память не роняет запись
                logger.warning("[prompt_release] кэш памяти не обновлён | "
                               "key=%s", spec.pg_key, exc_info=True)
        if scope == "chat" and applied and chat_id is not None:
            try:
                from services.chat_params import get_chat_params_cache
                chat_cache = get_chat_params_cache()
                if chat_cache is not None:
                    await chat_cache.invalidate_chat(int(chat_id))
            except Exception:      # pragma: no cover — fail-open
                logger.debug("[prompt_release] chat cache invalidate failed",
                             exc_info=True)

    logger.info("[prompt_release] write_prompt_values | scope=%s | chat=%s | "
                "applied=%d | skipped_same=%d | rejected=%d | kind=%s | "
                "actor=%s", scope, chat_id, len(applied), len(skipped),
                len(rejected), kind, str(actor or ""))
    return {"applied": applied, "skipped_same": skipped,
            "rejected": rejected, "prompt_snapshots": snapshots,
            "chat_updated_at": chat_updated_at, "journal_recorded": True}


def _meme_template_violation(spec, text: str) -> str:
    """Гейт шаблона мема (≥2 ``{joke}``) — тот же, что у спец-эндпоинта."""
    from services import meme_initiative as mi
    if spec.pg_key != mi.prompt_setting_key(mi.IMAGE_PROMPT_BLOCK_ID):
        return ""
    try:
        return str(mi.template_validation_error(text) or "")
    except Exception:          # pragma: no cover — гейт не роняет запись
        return ""


async def write_versioned_value(block_id: str, text: str, *, cache=None,
                                store=None, scope: str = "global",
                                chat_id: int | None = None, actor=None,
                                reason: str = "",
                                kind: str = "manual_edit") -> dict:
    """Тонкая обёртка над :func:`write_prompt_values` (совместимость вызовов).

    Возвращает историческую форму ответа одиночной записи (``applied`` как
    признак, ``revision_id``, ``sha256_12``, ``outcome``,
    ``factory_revision_applied``). Журнал недоступен →
    :class:`JournalUnavailable` (значение не пишется).
    """
    spec = pr.block(block_id) or pr.by_pg_key(block_id)
    if spec is None or not spec.pg_key:
        return {"applied": False, "reason": "block_not_pg_managed",
                "block_id": block_id}
    result = await write_prompt_values(
        [PromptWriteItem(block_id=spec.block_id, text=str(text or ""))],
        scope=scope, chat_id=chat_id, cache=cache, store=store, actor=actor,
        reason=reason, kind=kind)
    if result["rejected"]:
        rejected = result["rejected"][0]
        payload = {"applied": False, "reason": rejected.get("reason", ""),
                   "block_id": spec.block_id, "pg_key": spec.pg_key,
                   "journal_recorded": False}
        if rejected.get("detail"):
            payload["detail"] = rejected["detail"]
        return payload
    applied = spec.pg_key in result["applied"]
    snapshot = next((row for row in result["prompt_snapshots"]
                     if row["key"] == spec.pg_key), {})
    state = await _read_applied_safe(store, spec.block_id, scope, chat_id)
    return {
        "applied": applied, "reason": "ok" if applied else "skipped_same",
        "block_id": spec.block_id, "pg_key": spec.pg_key, "scope": scope,
        "chat_id": chat_id,
        "revision_id": snapshot.get("revision_id", ""),
        "sha256_12": snapshot.get("sha256_12", ""),
        "factory_revision_applied": (state.factory_revision_applied
                                     if state is not None else ""),
        "outcome": "applied" if applied else "skipped_same",
        "journal_recorded": True,
        "prompt_snapshots": result["prompt_snapshots"],
        "chat_updated_at": result["chat_updated_at"],
    }


async def _read_applied_safe(store, block_id: str, scope: str,
                             chat_id: int | None):
    try:
        return await store.read_applied(block_id, scope, chat_id)
    except Exception:          # pragma: no cover — чтение указателя не критично
        return None


def _doc_with_field_public(document: dict, field_name: str, text: str) -> dict:
    from services.prompt_factory import _doc_with_field
    return _doc_with_field(document, field_name, text, set_level=True)


async def _read_override_value(store, chat_id: int, pg_key: str) -> str | None:
    for chat_id_, value in await store.iter_chat_overrides(pg_key):
        if chat_id_ == chat_id:
            return value
    return None


async def remove_prompt_override(block_id: str, *, chat_id: int, actor=None,
                                 cache=None, store=None, pg=None,
                                 reason: str = "chat_override_removed",
                                 expected_updated_at: str | None = None) -> dict:
    """Снять чатовый override со снимком текста (контракт §3.6).

    Одна транзакция под теми же локами: текущий override читается из PG;
    последний действующий собственный текст сохраняется ревизией (если такой
    ревизии ещё нет) + событие ``kind='chat_inherit_reset'``,
    ``outcome='recorded'``; ключ удаляется тем же ``set_chat_params`` на
    коннекте транзакции. Активный указатель не двигается — чат наследует
    global effective. Журнал недоступен → :class:`JournalUnavailable`.
    """
    spec = pr.block(block_id) or pr.by_pg_key(block_id)
    if spec is None or not spec.pg_key:
        return {"applied": False, "reason": "block_not_pg_managed",
                "block_id": block_id}
    store = store if store is not None else default_journal(cache)
    if store is None:
        raise JournalUnavailable(
            "журнал версий недоступен: override не снят")
    try:
        await store.ensure_journal()
    except Exception as exc:
        raise JournalUnavailable(
            f"журнал версий недоступен: {type(exc).__name__}") from exc

    chat_key = int(chat_id)
    revision_id = ""
    with journal_write_scope([JournalWriteGrant(spec.block_id, "chat",
                                                chat_key)]):
        async with store.apply_lock():
            async with store.transaction():
                state_row = await store.read_chat_state(chat_key, pg=pg)
                overrides = dict((state_row or {}).get("overrides") or {})
                if state_row is None or spec.pg_key not in overrides:
                    return {"applied": False, "reason": "no_chat_override",
                            "block_id": block_id, "pg_key": spec.pg_key,
                            "scope": "chat", "chat_id": chat_key}
                raw = overrides.get(spec.pg_key)
                last_text = (_block_text_value(spec, raw) or "")
                applied_state = await store.read_applied(
                    spec.block_id, "chat", chat_key)
                if last_text.strip():
                    # Идемпотентно по revision_id: если байты уже есть в
                    # истории — новой ревизии не появляется, событие остаётся.
                    revision = await _insert_revision_once(
                        store, spec, origin="manual", body=last_text,
                        scope="chat", chat_id=chat_key, actor=str(actor or ""),
                        reason=reason)
                    revision_id = revision.revision_id
                overrides.pop(spec.pg_key, None)
                meta = dict((state_row or {}).get("meta") or {})
                meta["updated_by"] = actor
                await store.write_chat_state(
                    chat_key, overrides, meta, changed_by=actor, pg=pg,
                    expected_updated_at=expected_updated_at)
                await store.insert_activation(ActivationRow(
                    block_id=spec.block_id, scope="chat", chat_id=chat_key,
                    revision_id=revision_id,
                    factory_revision_applied=(
                        applied_state.factory_revision_applied
                        if applied_state is not None else ""),
                    kind="chat_inherit_reset", outcome="recorded",
                    release_id="", actor=str(actor or ""), detail_code=reason))
    try:
        from services.chat_params import get_chat_params_cache
        chat_cache = get_chat_params_cache()
        if chat_cache is not None:
            await chat_cache.invalidate_chat(chat_key)
    except Exception:          # pragma: no cover — fail-open
        logger.debug("[prompt_release] chat cache invalidate failed",
                     exc_info=True)
    logger.info("[prompt_release] chat override removed | block=%s | chat=%s "
                "| revision=%s | actor=%s", spec.block_id, chat_key,
                revision_id, str(actor or ""))
    return {"applied": True, "block_id": block_id, "pg_key": spec.pg_key,
            "scope": "chat", "chat_id": chat_key, "revision_id": revision_id,
            "factory_value_written": False, "global_value_written": False}


async def capture_pre_versioning_values(store, cache=None) -> int:
    """Захватить ДЕЙСТВУЮЩИЕ ручные байты до первой версионированной записи.

    Шаг внутри ``apply_release`` (та же транзакция и лок), сразу после импорта
    старой истории (контракт §3.7): для каждого PG-блока и каждого
    существующего чатового override, у которых текущих байтов НЕТ ни в одной
    ревизии этого scope, вставляется ревизия ``origin='legacy'``,
    ``reason='pre_versioning_import'``, время импорта = now, и событие
    ``kind='legacy_import'``, ``outcome='recorded'``. Действующий текст,
    активный указатель и ``factory_revision_applied`` не меняются; повтор
    идемпотентен по ``revision_id``.

    Возвращает число захваченных значений.
    """
    captured = 0
    for spec in sorted(pr.all_blocks(), key=lambda s: s.block_id):
        if not spec.pg_key:
            continue
        try:
            raw = await store.read_global(spec.pg_key)
        except Exception:      # pragma: no cover — чтение слоя не роняет старт
            logger.debug("[prompt_release] capture: read failed | key=%s",
                         spec.pg_key, exc_info=True)
            continue
        text = _block_text_value(spec, raw)
        if text and text.strip():
            if await _capture_value_once(store, spec, text, scope="global",
                                         chat_id=None):
                captured += 1
        try:
            chat_values = await store.iter_chat_overrides(spec.pg_key)
        except Exception:      # pragma: no cover
            continue
        for chat_id, value in chat_values:
            chat_text = _block_text_value(spec, value)
            if chat_text and chat_text.strip():
                if await _capture_value_once(store, spec, chat_text,
                                             scope="chat",
                                             chat_id=int(chat_id)):
                    captured += 1
    if captured:
        logger.info("[prompt_release] pre_versioning capture | values=%d",
                    captured)
    return captured


async def _capture_value_once(store, spec, text: str, *, scope: str,
                              chat_id: int | None) -> bool:
    """Одна запись захвата: ревизия legacy + событие recorded (или no-op)."""
    sha = pr.sha12(text)
    for origin in pr.REVISION_ORIGINS:
        existing = await store.get_revision(
            pr.revision_id_for(spec.block_id, scope, chat_id, origin, sha))
        if existing is not None:
            return False           # байты уже известны истории этого scope
    revision = await _insert_revision_once(
        store, spec, origin="legacy", body=text, scope=scope, chat_id=chat_id,
        actor="", reason="pre_versioning_import")
    await store.insert_activation(ActivationRow(
        block_id=spec.block_id, scope=scope, chat_id=chat_id,
        revision_id=revision.revision_id, factory_revision_applied="",
        kind="legacy_import", outcome="recorded", release_id="", actor="",
        detail_code="pre_versioning_import"))
    return True


def _foreign_scope_reason(revision, scope: str,
                          chat_id: int | None) -> str:
    """Почему ревизия не принадлежит запрошенному scope ("" — принадлежит).

    Чужой чат/scope не активируется: перенос текста между scope — это НОВАЯ
    ревизия целевого scope (``origin='restored'``, §2.4 п.8), а не
    перепривязка чужого ``revision_id`` (§7.3 п.6).
    """
    rev_scope = str(getattr(revision, "scope", "") or "")
    request_scope = str(scope or "global")
    if rev_scope == "chat":
        if request_scope != "chat" or \
                int(getattr(revision, "chat_id", 0) or 0) != int(chat_id or 0):
            return "revision_foreign_scope"
        return ""
    if request_scope == "chat":
        return "revision_foreign_scope"
    if rev_scope == "code" and request_scope != "code":
        return "revision_foreign_scope"
    if rev_scope == "global" and request_scope == "code":
        return "revision_foreign_scope"
    return ""


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
    foreign = _foreign_scope_reason(revision, scope, chat_id)
    if foreign:
        # §7.3 п.6: чужой scope/чат не активируется — ни одного изменения.
        logger.warning("[prompt_release] %s | block=%s | revision=%s | "
                       "revision_scope=%s/%s | requested=%s/%s", foreign,
                       spec.block_id, revision_id, revision.scope,
                       revision.chat_id, scope, chat_id)
        return {"applied": False, "reason": foreign, "block_id": block_id,
                "revision_id": revision_id, "revision_scope": revision.scope,
                "revision_chat_id": revision.chat_id}
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
    # Ревью F2: активация указывает на ЗАПРОШЕННУЮ ревизию — клона origin=manual
    # не создаётся; байты записываются, origin сохраняется у самой ревизии
    # (rollback на manual-правку остаётся manual, forward на заводскую —
    # factory); ``factory_revision_applied`` не сбрасывается.
    #
    # P0-2 (01.11.2026): активное состояние читается ВНУТРИ транзакции — под
    # тем же advisory-локом, который сериализует активации. Прежнее чтение до
    # транзакции могло классифицировать параллельный выбор как откат/вперёд по
    # устаревшему состоянию и записать неверный factory_revision_applied.
    async with store.transaction() as tx:
        try:
            state = await store.read_applied(spec.block_id, scope, chat_id)
            kind = "manual_rollback"
            if state is not None and state.revision_id and \
                    state.revision_id != revision_id:
                # Детерминированный порядок (вставка ревизий в журнал), не
                # часы: цель создана раньше активной → откат; позже или
                # порядок неизвестен → возврат вперёд (EVOL-017).
                precedes = await store.revision_precedes(revision_id,
                                                         state.revision_id)
                kind = "manual_rollback" if precedes else "manual_forward"
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
            with journal_write_scope([JournalWriteGrant(spec.block_id,
                                                       "global", None)]):
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
    Ревью F4: доступ через hook полномочий (checker, иначе непустой actor).

    P0-2 (01.11.2026): сбой чтения журнала поднимает
    :class:`JournalUnavailable` (HTTP-слой отдаёт 503) — история не
    подменяется пустым списком.
    """
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
        except Exception as exc:
            # Ревью P0-2 (01.11.2026): раньше сбой чтения журнала глотался и
            # отдавался ПУСТОЙ список — история выглядела «пустой», хотя она
            # есть (запрещено скрывать отказ под пустым массивом). Теперь
            # вызывающий получает честный JournalUnavailable (HTTP 503).
            logger.warning("[prompt_release] список ревизий недоступен",
                           exc_info=True)
            raise JournalUnavailable(
                f"journal read failed: {type(exc).__name__}") from exc
    active = None
    if state is not None and state.revision_id:
        rev = await store.get_revision(state.revision_id)
        if rev is not None:
            active = {"revision_id": rev.revision_id, "origin": rev.origin,
                      "sha256_12": rev.content_sha12,
                      "chars": len(rev.body or ""),
                      "created_at": rev.created_at,
                      "factory_revision_applied":
                          state.factory_revision_applied}
    rows: list[dict] = []
    for r in revisions:
        rows.append({
            "revision_id": r.revision_id, "origin": r.origin,
            "sha256_12": r.content_sha12, "chars": _revision_chars(r),
            "factory_revision": r.factory_revision,
            "release_id": r.release_id, "actor": r.actor, "reason": r.reason,
            "retired": r.retired, "created_at": r.created_at,
            "schema_compat": r.schema_compat,
            # global/chat и адресат ревизии видны в строке истории.
            "scope": r.scope, "chat_id": r.chat_id,
        })
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
        "revisions": rows,
        "activations": [{
            "kind": a.kind, "outcome": a.outcome,
            "revision_id": a.revision_id, "scope": a.scope,
            "chat_id": a.chat_id, "release_id": a.release_id,
            "actor": a.actor, "detail_code": a.detail_code,
            "created_at": a.created_at,
        } for a in activations],
    }


def _revision_chars(revision: RevisionRow) -> int:
    """Длина текста ревизии без загрузки тела из журнала.

    Ревью P0-2 (01.11.2026, продовый HTTP 500 «История версий»): прежняя
    версия звала ``store.get_revision(...)`` БЕЗ ``await`` и падала с
    ``AttributeError: 'coroutine' object has no attribute 'body'`` на любом
    реальном PG-журнале (список ревизий тела не отдаёт — ``body=""``).
    Тестовый ``MemoryPromptJournal`` отдавал тело в списке, поэтому дефект
    не ловился. Теперь длина приходит из стора (``chars``) либо из тела.
    """
    if revision.chars is not None:
        return int(revision.chars)
    return len(revision.body or "")


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
    "LOCK_TIMEOUT_SQL", "NON_TEXT_VALUE_KEYS",
    "RevisionRow", "ActivationRow", "AppliedState", "BlockReleaseResult",
    "PromptWriteItem", "JournalWriteGrant",
    "JournalUnavailable", "PromptJournalError", "PromptPermissionError",
    "PromptJournalBypass",
    "PermissionChecker", "set_permission_checker", "check_permission",
    "journal_write_scope", "journal_write_granted", "legacy_migration_write",
    "assert_prompt_write_allowed",
    "MemoryPromptJournal", "PgPromptJournal", "default_journal",
    "apply_release", "write_prompt_values", "write_versioned_value",
    "remove_prompt_override", "capture_pre_versioning_values",
    "activate_revision", "list_versions", "get_revision_source",
    "diff_revisions",
]
