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
import base64
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
#: Поиск ревизии по байтам текста (откат из истории, §2.2 п.5): адресат —
#: та же семантика фильтра, что и у списков (чужой чат не находится).
_GET_REVISION_BY_SHA_SQL = """
SELECT revision_id, block_id, pg_key, scope, chat_id, origin, content_sha12,
       body, factory_revision, schema_compat, release_id, actor, reason,
       source_updated_at, retired, created_at
FROM prompt_revisions
WHERE block_id = $1 AND content_sha12 = $2
  AND (chat_id = $3 OR (chat_id IS NULL AND $3 IS NULL))
ORDER BY COALESCE(created_at, 'epoch'::timestamptz) DESC, revision_id DESC
LIMIT 1
"""

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
#: Страницы полной истории (EPIC-PROMPT-VERSIONING-UX-01 §3.5): keyset по
#: ``(created_at, вторичный ключ)`` — БЕЗ OFFSET и без потолка по числу строк.
#: Каждый запрос читает не больше ``page_size + 1`` строк одной таблицы, поэтому
#: тысяча ревизий не превращается в тысячу строк ответа.
_PAGE_REVISIONS_DESC_SQL = """
SELECT revision_id, origin, actor, scope, chat_id, retired, schema_compat,
       content_sha12, length(body) AS char_count, reason, release_id,
       factory_revision, created_at
FROM prompt_revisions
WHERE block_id = $1 AND (chat_id = $2 OR (chat_id IS NULL AND $2 IS NULL))
  AND ($3::timestamptz IS NULL
       OR (COALESCE(created_at, 'epoch'::timestamptz), revision_id)
          < ($3::timestamptz, $4::text))
ORDER BY COALESCE(created_at, 'epoch'::timestamptz) DESC, revision_id DESC
LIMIT $5
"""
#: Статус события считается по РЕВИЗИИ, на которую оно ссылается (§2.4 п.9):
#: поэтому ``retired``/``schema_compat`` приезжают в той же странице через
#: LEFT JOIN по первичному ключу ревизии. Отдельного запроса на строку нет, а
#: тело ревизии по-прежнему не читается (колонка ``body`` не выбирается).
_PAGE_ACTIVATIONS_DESC_SQL = """
SELECT a.activation_id, a.revision_id, a.scope, a.chat_id, a.kind, a.outcome,
       a.release_id, a.actor, a.detail_code, a.created_at,
       COALESCE(r.retired, false) AS retired,
       COALESCE(r.schema_compat, '') AS schema_compat
FROM prompt_activations a
LEFT JOIN prompt_revisions r ON r.revision_id = a.revision_id
WHERE a.block_id = $1
  AND (a.chat_id = $2 OR (a.chat_id IS NULL AND $2 IS NULL))
  AND ($3::timestamptz IS NULL
       OR (COALESCE(a.created_at, 'epoch'::timestamptz),
           ('act:' || lpad(a.activation_id::text, 20, '0')))
          < ($3::timestamptz, $4::text))
ORDER BY COALESCE(a.created_at, 'epoch'::timestamptz) DESC, a.activation_id DESC
LIMIT $5
"""

#: Действующий owner baseline = ПОСЛЕДНЕЕ событие назначения/снятия по
#: ``activation_id`` для (block_id, scope, chat_id) (контракт §2.1). Новых
#: таблиц/колонок нет: baseline — событие существующего журнала, тело текста
#: не копируется.
_BASELINE_SQL = """
SELECT activation_id, revision_id, kind, actor, detail_code, created_at
FROM prompt_activations
WHERE block_id = $1 AND scope = $2
  AND (chat_id = $3 OR (chat_id IS NULL AND $3 IS NULL))
  AND kind IN ('baseline_assign', 'baseline_clear')
ORDER BY activation_id DESC LIMIT 1
"""
#: Виды событий, из которых читается owner baseline (порядок не важен).
_BASELINE_KINDS = ("baseline_assign", "baseline_clear")
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


@dataclass
class BaselineEvent:
    """Событие журнала, задающее owner baseline (контракт §2.1).

    ``kind='baseline_assign'`` + непустой ``revision_id`` — назначено;
    ``kind='baseline_clear'`` — назначение снято (явное снятие, а не «не
    было»). Тело текста здесь отсутствует: baseline — указатель.
    """

    block_id: str
    scope: str
    kind: str                      # baseline_assign | baseline_clear
    revision_id: str = ""
    chat_id: int | None = None
    actor: str = ""
    detail_code: str = ""
    created_at: str = ""
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
# Полная история страницами (EPIC-PROMPT-VERSIONING-UX-01 §3.5, §2.2 п.3)
# ═══════════════════════════════════════════════════════════════════════════
#: Размер страницы по умолчанию. Это НЕ потолок истории: сколько всего
#: страниц — решает число записей в журнале (§3.5 ТЗ: «Не ограничивать число
#: сохраняемых ревизий... Список читать страницами»).
HISTORY_PAGE_DEFAULT = 50
#: Верхняя граница ОДНОГО ответа (защита канала), а не истории: клиент листает
#: дальше тем же курсором. Прежний `LIMIT 50` обрезал саму историю и после 50
#: событий терял всё остальное — этого больше нет.
HISTORY_PAGE_MAX = 200

#: Порядок строк в ответе. Объединённая лента (`entries`) — от новых к старым;
#: `revisions` сохраняет исторический порядок ASC, `activations` — DESC.
HISTORY_ORDER_NEWEST = "newest_first"
HISTORY_ORDER_OLDEST = "oldest_first"

#: Человекочитаемые источники ревизии (§2.2 п.3): `manual` | `imported` |
#: `from_release` | `restored` | `legacy`. Токен машинный, подпись — русская.
REVISION_SOURCES = ("manual", "imported", "from_release", "restored", "legacy")
_SOURCE_BY_ORIGIN = {
    "manual": "manual",
    "legacy": "imported",        # снимок прежних байтов при захвате/импорте
    "factory": "from_release",   # заводская поставка из релиза кода
    "restored": "restored",      # возврат/копирование сохранённого текста
}
_SOURCE_LABELS = {
    "manual": "ручная",
    "imported": "импортирована",
    "from_release": "из релиза",
    "restored": "восстановлена",
    "legacy": "до версионирования",
}

#: Статус записи истории (§2.2 п.3, §2.5). `retired`/`incompatible` читаются и
#: сравниваются, но НИКОГДА не активируются и не назначаются базовыми (§2.4 п.9).
REVISION_STATUSES = ("active", "baseline", "inactive", "incompatible", "retired")
_STATUS_LABELS = {
    "active": "активная",
    "baseline": "базовая",
    "inactive": "неактивная",
    "incompatible": "несовместимая",
    "retired": "снята с регистрации",
}

#: Записи объединённой ленты истории.
ENTRY_REVISION = "revision"
ENTRY_ACTIVATION = "activation"


def _norm_ts(value) -> str:
    """Нормализованная ISO-метка для сравнения/сортировки в обоих сторах.

    PG отдаёт ``datetime``, двойник — строку: приводим к одному виду (UTC,
    микросекунды), иначе порядок «новые сверху» разъезжается между сторами.
    """
    if isinstance(value, datetime.datetime):
        dt = value
    else:
        dt = _parse_ts(str(value or ""))
    if dt is None:
        return str(value or "")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).isoformat(
        timespec="microseconds")


def clamp_page_size(value, default: int = HISTORY_PAGE_DEFAULT) -> int:
    """Размер страницы из запроса: 1..``HISTORY_PAGE_MAX`` (иначе значение по
    умолчанию). Некорректный ввод не роняет историю — просто дефолт."""
    try:
        size = int(value)
    except (TypeError, ValueError):
        return int(default)
    if size <= 0:
        return int(default)
    return max(1, min(size, HISTORY_PAGE_MAX))


def encode_history_cursor(created_at, sort_id: str, rank: int) -> str:
    """Непрозрачный курсор страницы: позиция + уже выданный порядковый номер.

    Курсор — keyset ``(created_at, sort_id)``: offset отсутствует, поэтому
    вставка новых строк не сдвигает уже показанные записи. ``rank`` едет в
    курсоре, чтобы «порядковый номер» не пересчитывался запросом COUNT и не
    «прыгал» при параллельных записях.
    """
    payload = json.dumps({"v": 1, "t": _norm_ts(created_at),
                          "i": str(sort_id), "r": int(rank)},
                         separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode(
        "ascii").rstrip("=")


def decode_history_cursor(raw: str | None) -> dict | None:
    """Разобрать курсор. ``ValueError`` — курсор испорчен (HTTP 422)."""
    text = str(raw or "").strip()
    if not text:
        return None
    padded = text + "=" * (-len(text) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except Exception as exc:
        raise ValueError("cursor_invalid") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise ValueError("cursor_invalid")
    ts = str(payload.get("t") or "")
    sort_id = str(payload.get("i") or "")
    if not ts or not sort_id:
        raise ValueError("cursor_invalid")
    try:
        rank = int(payload.get("r") or 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("cursor_invalid") from exc
    return {"ts": ts, "sort_id": sort_id, "rank": max(1, rank)}


def activation_sort_id(activation_id: int) -> str:
    """Стабильный вторичный ключ события: ``act:<20 цифр>`` (сортируется как
    строка и не зависит от текущего максимума sequence)."""
    return "act:%020d" % int(activation_id or 0)


@dataclass
class HistoryRow:
    """Сырая запись объединённой истории (ревизия или событие активации).

    Тело текста здесь НИКОГДА не заполняется: список отдаёт только метаданные,
    полный текст читается отдельным авторизованным запросом
    (:func:`get_revision_source`) — §3.7 ТЗ, «не возвращать тела в списках».
    """

    entry_type: str                  # revision | activation
    created_at: str                  # исходная метка стора (ISO)
    sort_id: str                     # вторичный ключ порядка
    revision_id: str = ""
    origin: str = ""
    actor: str = ""
    scope: str = "global"
    chat_id: int | None = None
    retired: bool = False
    schema_compat: str = ""
    content_sha12: str = ""
    chars: int = 0
    reason: str = ""
    release_id: str = ""
    factory_revision: str = ""
    kind: str = ""                   # для событий: ACTIVATION_KINDS
    outcome: str = ""                # для событий: ACTIVATION_OUTCOMES
    detail_code: str = ""
    activation_id: int = 0


@dataclass
class HistoryPage:
    """Одна страница истории + курсор следующей."""

    rows: list
    next_cursor: str = ""
    has_more: bool = False
    rank_start: int = 1


def _history_key(row) -> tuple:
    return (_norm_ts(row.created_at), str(row.sort_id))


def _history_after_cursor(row, cursor: dict | None) -> bool:
    """Строка НОВЕЕ курсора (её ещё не показывали)? Нужно для порядковых номеров."""
    if cursor is None:
        return True
    return _history_key(row) > (cursor["ts"], cursor["sort_id"])


def _history_page_of(rev_rows: list, act_rows: list, cursor: dict | None,
                     page_size: int) -> HistoryPage:
    """Слить два потока (оба — «старые сверху уже отфильтрованы») в страницу.

    Каждый стор отдаёт не больше ``page_size + 1`` строк своей таблицы старше
    курсора, поэтому объединённая верхушка страницы всегда внутри их
    объединения (k-way merge без полного чтения таблиц).
    """
    rank_start = int((cursor or {}).get("rank") or 1)
    merged = [r for r in (list(rev_rows) + list(act_rows))
              if cursor is None or _history_key(r) < (cursor["ts"],
                                                      cursor["sort_id"])]
    merged.sort(key=_history_key, reverse=True)
    page = merged[:page_size]
    has_more = len(merged) > page_size
    next_cursor = ""
    if has_more and page:
        last = page[-1]
        next_cursor = encode_history_cursor(last.created_at, last.sort_id,
                                            rank_start + len(page))
    return HistoryPage(rows=page, next_cursor=next_cursor,
                       has_more=has_more, rank_start=rank_start)


def history_source(origin: str, *, kind: str = "") -> str:
    """Токен источника записи истории (§2.2 п.3)."""
    token = _SOURCE_BY_ORIGIN.get(str(origin or ""))
    if token:
        return token
    if kind == "legacy_import":
        return "imported"
    if kind in ("deploy_activate",):
        return "from_release"
    if kind in ("baseline_assign", "baseline_clear", "baseline_restore",
                "factory_restore"):
        return "restored"
    if kind in ("manual_edit", "manual_rollback", "manual_forward"):
        return "manual"
    return "legacy"


#: Подписи СОБЫТИЙ, у которых «источник текста» не применим (§2.2 п.3):
#: назначение/снятие owner baseline ничего не восстанавливает — меняется
#: указатель. Токен ``source`` при этом остаётся контрактным, уточняется только
#: человеческая подпись строки (иначе базовое назначение читалось как
#: «восстановлена», хотя текст не восстанавливался).
_EVENT_SOURCE_LABELS = {
    "baseline_assign": "назначена базовая",
    "baseline_clear": "назначение базовой снято",
}


def history_source_label(token: str, *, kind: str = "") -> str:
    kind = str(kind or "")
    if kind in _EVENT_SOURCE_LABELS:
        return _EVENT_SOURCE_LABELS[kind]
    return _SOURCE_LABELS.get(str(token or ""), "неизвестный источник")


def history_status(*, retired: bool = False, schema_compat: str = "",
                   revision_id: str = "", active_id: str = "",
                   baseline_id: str = "") -> str:
    """Статус записи: retired > incompatible > active > baseline > inactive.

    Совместимость проверяется раньше «активности»: несовместимая/снятая
    ревизия не бывает действием, даже если указатель на неё остался (§2.4 п.9).
    """
    if retired:
        return "retired"
    if schema_compat and schema_compat not in SUPPORTED_SCHEMA_COMPAT:
        return "incompatible"
    if revision_id and revision_id == active_id:
        return "active"
    if revision_id and revision_id == baseline_id:
        return "baseline"
    return "inactive"


def history_status_label(status: str) -> str:
    return _STATUS_LABELS.get(str(status or ""), str(status or ""))


def history_reason_text(status: str, *, schema_compat: str = "",
                        detail_code: str = "") -> str:
    """Почему запись недействительна — человеческим языком (не пустой текст)."""
    if status == "retired":
        return ("Версия снята с регистрации (retired): её можно читать и "
                "сравнивать, но нельзя применить или назначить базовой.")
    if status == "incompatible":
        schema = schema_compat or "не указана"
        return (f"Несовместима с текущей схемой <{schema}>: читать и "
                "сравнивать можно, применять и назначать базовой — нельзя.")
    if detail_code in ("factory_superseded_pinned",):
        return ("Закреплённый владельцем промпт: новая заводская версия "
                "записана в историю, действующий текст сохранён.")
    if detail_code in ("factory_same", "restart_same_revision"):
        return "Текст совпал с действующим: применять нечего."
    if detail_code in ("legacy_snapshot", "legacy_empty"):
        return "Служебный снимок прежних байтов при первом включении журнала."
    return ""


def _status_of_row(row, active_id: str = "", baseline_id: str = "") -> str:
    return history_status(retired=bool(row.retired),
                          schema_compat=str(row.schema_compat or ""),
                          revision_id=str(row.revision_id or ""),
                          active_id=str(active_id or ""),
                          baseline_id=str(baseline_id or ""))


# ═══════════════════════════════════════════════════════════════════════════
# Эффективное состояние (PVR-FC-CORRECTIVE-01 §PVR-01): что РЕАЛЬНО действует
# ═══════════════════════════════════════════════════════════════════════════

#: Откуда реально взят текст для выбранного чата. ``code`` — заводская
#: константа (нет сохранённого слоя, поле документа пусто или значение
#: удержано провенансом).
EFFECTIVE_ORIGINS = ("chat_override", "global", "code")
_EFFECTIVE_ORIGIN_LABELS = {
    "chat_override": "локальная версия чата",
    "global": "глобальная версия",
    "code": "исходная из кода",
}

#: Статус сопоставления действующего текста с журналом. ``unmatched`` —
#: текст действует, но сохранённой ревизии с такими байтами нет (честный
#: отдельный статус, НЕ «визуально ближайшая» ревизия); ``drift`` —
#: журнальный указатель ссылается на ревизию с другими байтами: до
#: разрешения расхождения ни одна ревизия не помечается действующей.
EFFECTIVE_STATE_STATUSES = ("matched", "unmatched", "drift", "unknown")
_EFFECTIVE_STATUS_LABELS = {
    "matched": "Действующий текст совпадает с сохранённой версией",
    "unmatched": "Не сопоставлено с историей",
    "drift": "Журнал и действующий текст расходятся",
    "unknown": "Состояние неизвестно (журнал недоступен)",
}


def effective_origin_label(origin: str) -> str:
    return _EFFECTIVE_ORIGIN_LABELS.get(str(origin or ""), str(origin or ""))


def effective_status_label(status: str) -> str:
    return _EFFECTIVE_STATUS_LABELS.get(str(status or ""), str(status or ""))


@dataclass(frozen=True)
class EffectiveState:
    """Эффективное состояние блока для выбранного чата (PVR-01).

    Поля вычисляются тем же резолвером, который собирает текущий
    LLM-payload (:func:`services.prompt_registry.effective_prompt`), по
    значениям персистентных слоёв из того же стора журнала, — не по
    истории и не по догадке UI. ``journal_*`` сюда НЕ входят: указатель
    журнала — отдельные поля ответа (PVR-01.3).
    """

    origin: str                    # chat_override | global | code | unknown
    content_hash: str              # sha256_12 сохранённого действующего текста
    revision_id: str | None = None  # сопоставленная ревизия (None — честно)
    status: str = "unknown"        # matched | unmatched | drift | unknown
    diagnostics: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "effective_origin": self.origin,
            "effective_origin_label": effective_origin_label(self.origin),
            "effective_content_hash": self.content_hash,
            "effective_revision_id": self.revision_id,
            "effective_status": self.status,
            "effective_status_label": effective_status_label(self.status),
            "effective_diagnostics": list(self.diagnostics),
        }


_UNKNOWN_EFFECTIVE_STATE = EffectiveState(
    origin="unknown", content_hash="", revision_id=None, status="unknown",
    diagnostics=("journal_unavailable",))


def history_event_status(*, retired: bool = False, schema_compat: str = "",
                         outcome: str = "") -> str:
    """Статус СОБЫТИЯ активации (PVR-02/C3.1): событие никогда не «active».

    Прошлое событие применения — «была применена», независимо от того, на
    какую ревизию оно ссылается и что действует сейчас. Снятая/несовместимая
    ревизия сохраняет свой статус и в событии (§2.4 п.9).
    """
    if retired:
        return "retired"
    if schema_compat and schema_compat not in SUPPORTED_SCHEMA_COMPAT:
        return "incompatible"
    if str(outcome or "") in ("applied", "skipped_same"):
        return "was_applied"
    return "event"


_EVENT_STATUS_LABELS = {
    "was_applied": "была применена",
    "event": "событие",
}


def history_event_status_label(status: str) -> str:
    if str(status or "") in _EVENT_STATUS_LABELS:
        return _EVENT_STATUS_LABELS[str(status)]
    return history_status_label(status)


def _effective_winning_value(spec, *, source: str, pg_value, chat_value,
                             chat_id: int | None):
    """Сырое сохранённое значение ВЫИГРАВШЕГО слоя (до чистки payload).

    ``(None, None)`` — действует заводская константа (слоя нет, поле
    документа пусто или значение удержано провенансом): байты — из кода.
    Иначе ``(текст, winner_chat)``: адресат, в котором живёт сопоставимая
    ревизия (chat-override → этот чат, global → глобальный адресат).
    """
    raw = chat_value if source == "chat" else (
        pg_value if source == "global" else None)
    if raw is None:
        return None, None
    if getattr(spec, "pg_doc_field", ""):
        field_text = pr.doc_field_text(_as_doc(raw), spec.pg_doc_field)
        if not field_text.strip():
            return None, None            # поле пусто → действует код
        return field_text, (int(chat_id) if source == "chat" else None)
    return str(raw), (int(chat_id) if source == "chat" else None)


async def resolve_effective_state(spec, *, scope: str, chat_id: int | None,
                                  store) -> EffectiveState:
    """Эффективное состояние для (block, scope, chat) тем же резолвером
    payload (PVR-01, PVR-01.1, PVR-01.2).

    Значения слоёв читаются из того же стора, откуда пайплайны берут
    активные байты (``bot_settings`` / chat-override), резолв —
    :func:`services.prompt_registry.effective_prompt` (per-chat override →
    global → код). Сопоставление с журналом — по байтам (sha256_12) в
    адресате выигравшего слоя; несопоставленный текст честно отдаёт
    ``revision_id=None`` со статусом «Не сопоставлено с историей».
    ``drift`` — журнальный указатель ссылается на ревизию с другими
    байтами (PVR-01.3: журнальные поля остаются журнальными, расхождение
    видно отдельным статусом, данные не портятся).
    """
    if store is None:
        return _UNKNOWN_EFFECTIVE_STATE
    pg_key = str(spec.pg_key or "")
    if not pg_key:
        # Кодовый блок: действует константа из кода (контракт §1.5);
        # сопоставление — по байтам константы в журнале.
        text = pr.factory_text(spec.block_id)
        content_hash = pr.sha12(text) if text else ""
        revision_id = None
        if content_hash:
            rev = await store.find_revision_by_sha(spec.block_id,
                                                   content_hash, chat_id=None)
            revision_id = rev.revision_id if rev is not None else None
        status = "matched" if revision_id is not None else "unmatched"
        return EffectiveState(origin="code", content_hash=content_hash,
                              revision_id=revision_id, status=status,
                              diagnostics=("code_managed_block",))
    pg_value = await store.read_global(pg_key)
    chat_value = None
    if chat_id is not None:
        state_row = await store.read_chat_state(int(chat_id))
        if state_row is not None:
            chat_value = (state_row.get("overrides") or {}).get(pg_key)
    eff = pr.effective_prompt(pg_key, pg_value=pg_value, chat_value=chat_value)
    diagnostics = [str(d) for d in eff.diagnostics]
    raw, winner_chat = _effective_winning_value(
        spec, source=str(eff.source), pg_value=pg_value, chat_value=chat_value,
        chat_id=chat_id)
    if raw is None:
        origin = "code"
        text = pr.factory_text(spec.block_id)
    else:
        origin = "chat_override" if eff.source == "chat" else "global"
        text = raw
    content_hash = pr.sha12(text) if text else ""
    revision_id = None
    if content_hash:
        rev = await store.find_revision_by_sha(spec.block_id, content_hash,
                                               chat_id=winner_chat)
        revision_id = rev.revision_id if rev is not None else None
    if revision_id is not None:
        status = "matched"
    else:
        status = "unmatched"
        diagnostics.append("effective_unmatched")
    return EffectiveState(origin=origin, content_hash=content_hash,
                          revision_id=revision_id, status=status,
                          diagnostics=tuple(diagnostics))


async def effective_drift(store, spec, *, scope: str, chat_id: int | None,
                          state: EffectiveState) -> tuple[bool, tuple]:
    """Расхождение журнального указателя с действующим текстом (PVR-01.3).

    ``True`` — указатель журнала ссылается на ревизию с ДРУГИМИ байтами,
    чем действует сейчас (или на несуществующую ревизию). Диагностика —
    только токены, без текстов промптов.
    """
    if store is None:
        return False, ()
    applied = await store.read_applied(spec.block_id, scope, chat_id)
    if applied is None or not str(applied.revision_id or ""):
        return False, ()
    diagnostics = []
    jrev = await store.get_revision(str(applied.revision_id))
    if jrev is None:
        diagnostics.append("journal_pointer_unknown_revision")
        return True, tuple(diagnostics)
    if str(jrev.content_sha12 or "") != str(state.content_hash or ""):
        diagnostics.append("journal_active_differs")
        return True, tuple(diagnostics)
    return False, tuple(diagnostics)

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

    async def read_baseline_event(self, block_id: str, scope: str,
                                  chat_id: int | None) -> "BaselineEvent | None":
        """Последнее событие baseline для адресата (иначе ``None``)."""
        found = None
        for idx, row in enumerate(self.activations):
            if (row.block_id == block_id and row.kind in _BASELINE_KINDS
                    and _scope_key(row.scope, row.chat_id)
                    == _scope_key(scope, chat_id)):
                found = (idx, row)
        if found is None:
            return None
        idx, row = found
        return BaselineEvent(block_id=row.block_id, scope=row.scope,
                             kind=row.kind, revision_id=row.revision_id or "",
                             chat_id=row.chat_id, actor=row.actor or "",
                             detail_code=row.detail_code or "",
                             created_at=row.created_at or "",
                             activation_id=idx + 1)

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

    # — страницы полной истории (§3.5): без потолка, только размер страницы —
    async def find_revision_by_sha(self, block_id: str, sha12: str, *,
                                   chat_id: int | None = None
                                   ) -> "RevisionRow | None":
        """Ревизия блока по ``sha256_12`` текста (для отката из истории).

        Идентичность ревизии определяется байтами, поэтому sha — законный
        ключ поиска; адресат фильтруется той же семантикой, что и списки
        (чужой чат не находится).
        """
        want = str(sha12 or "")
        if not want:
            return None
        found = None
        for row in self.revisions.values():
            if (row.block_id == block_id and row.content_sha12 == want
                    and _row_matches_chat(row, chat_id)):
                if found is None or (
                        _norm_ts(row.created_at), row.revision_id) > (
                        _norm_ts(found.created_at), found.revision_id):
                    found = row
        return RevisionRow(**vars(found)) if found is not None else None

    def _history_rows(self, block_id: str,
                      chat_id: int | None) -> tuple[list, list]:
        revs = [HistoryRow(
            entry_type=ENTRY_REVISION, created_at=_norm_ts(r.created_at),
            sort_id=str(r.revision_id), revision_id=r.revision_id,
            origin=r.origin, actor=r.actor, scope=r.scope, chat_id=r.chat_id,
            retired=bool(r.retired), schema_compat=r.schema_compat or "",
            content_sha12=r.content_sha12, chars=len(r.body or ""),
            reason=r.reason, release_id=r.release_id,
            factory_revision=r.factory_revision)
            for r in self.revisions.values()
            if r.block_id == block_id and _row_matches_chat(r, chat_id)]
        acts = []
        for idx, a in enumerate(self.activations):
            if a.block_id != block_id or not _row_matches_chat(a, chat_id):
                continue
            # Статус события — статус СВЯЗАННОЙ ревизии (§2.4 п.9): иначе строка
            # события и строка той же версии показывали бы разное состояние.
            linked = self.revisions.get(a.revision_id) if a.revision_id else None
            acts.append(HistoryRow(
                entry_type=ENTRY_ACTIVATION,
                created_at=_norm_ts(a.created_at),
                sort_id=activation_sort_id(idx + 1), revision_id=a.revision_id,
                actor=a.actor, scope=a.scope, chat_id=a.chat_id,
                retired=bool(linked.retired) if linked is not None else False,
                schema_compat=(linked.schema_compat or "")
                if linked is not None else "",
                reason=a.detail_code, release_id=a.release_id, kind=a.kind,
                outcome=a.outcome, detail_code=a.detail_code,
                activation_id=idx + 1))
        return revs, acts

    async def list_history_page(self, block_id: str, *,
                               chat_id: int | None = None,
                               cursor: dict | None = None,
                               page_size: int = HISTORY_PAGE_DEFAULT
                               ) -> HistoryPage:
        size = clamp_page_size(page_size)
        revs, acts = self._history_rows(block_id, chat_id)
        return _history_page_of(revs, acts, cursor, size)

    async def list_revisions_page(self, block_id: str, *,
                                  chat_id: int | None = None,
                                  cursor: dict | None = None,
                                  page_size: int = HISTORY_PAGE_DEFAULT
                                  ) -> dict:
        """Ревизии страницей: первая страница — САМЫЕ НОВЫЕ, вглубь — старее.

        Внутри страницы строки идут в историческом порядке ASC (старые сверху),
        как их и показывал EVOL-017; курсор ведёт вглубь истории, поэтому самая
        свежая правка не прячется за первой сотней старых (§3.5 ТЗ).
        """
        size = clamp_page_size(page_size)
        revs, _ = self._history_rows(block_id, chat_id)
        revs.sort(key=_history_key, reverse=True)
        rank_start = int((cursor or {}).get("rank") or 1)
        rows = [r for r in revs
                if cursor is None or _history_key(r) < (cursor["ts"],
                                                        cursor["sort_id"])]
        page = rows[:size]
        has_more = len(rows) > size
        next_cursor = (encode_history_cursor(page[-1].created_at,
                                             page[-1].sort_id,
                                             rank_start + len(page))
                       if has_more and page else "")
        return {"rows": list(reversed(page)), "next_cursor": next_cursor,
                "has_more": has_more, "rank_start": rank_start}

    async def list_activations_page(self, block_id: str, *,
                                    chat_id: int | None = None,
                                    cursor: dict | None = None,
                                    page_size: int = HISTORY_PAGE_DEFAULT
                                    ) -> dict:
        """События активаций страницей: новые сверху (как было в EVOL-017)."""
        size = clamp_page_size(page_size)
        _, acts = self._history_rows(block_id, chat_id)
        acts.sort(key=_history_key, reverse=True)
        rank_start = int((cursor or {}).get("rank") or 1)
        rows = [r for r in acts
                if cursor is None or _history_key(r) < (cursor["ts"],
                                                        cursor["sort_id"])]
        page = rows[:size]
        has_more = len(rows) > size
        next_cursor = (encode_history_cursor(page[-1].created_at,
                                             page[-1].sort_id,
                                             rank_start + len(page))
                       if has_more and page else "")
        return {"rows": page, "next_cursor": next_cursor,
                "has_more": has_more, "rank_start": rank_start}

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

    async def read_baseline_event(self, block_id: str, scope: str,
                                  chat_id: int | None) -> "BaselineEvent | None":
        """Последнее событие baseline по ``activation_id`` (§2.1).

        Внутри транзакции читается на её коннекте (``_run_on_conn``) — гонка
        с параллельным назначением невозможна: назначение и поставка
        сериализованы тем же advisory-локом.
        """
        async def _run(conn):
            return await conn.fetchrow(_BASELINE_SQL, block_id, scope, chat_id)
        row = await self._run_on_conn(_run)
        if row is None:
            return None
        return BaselineEvent(block_id=block_id, scope=scope,
                             kind=row["kind"], revision_id=row["revision_id"] or "",
                             chat_id=chat_id, actor=row["actor"] or "",
                             detail_code=row["detail_code"] or "",
                             created_at=str(row["created_at"] or ""),
                             activation_id=int(row["activation_id"]))

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

    async def find_revision_by_sha(self, block_id: str, sha12: str, *,
                                   chat_id: int | None = None
                                   ) -> "RevisionRow | None":
        """Ревизия блока по ``sha256_12`` текста (откат из истории, §2.2 п.5)."""
        want = str(sha12 or "")
        if not want:
            return None
        await self.ensure_journal()

        async def _run(conn):
            return await conn.fetchrow(_GET_REVISION_BY_SHA_SQL, block_id,
                                        want, chat_id)
        rec = await self._run_on_conn(_run)
        if rec is None:
            return None
        return RevisionRow(
            revision_id=rec["revision_id"], block_id=rec["block_id"],
            scope=rec["scope"], origin=rec["origin"],
            content_sha12=rec["content_sha12"], body=rec["body"] or "",
            pg_key=rec["pg_key"] or "", chat_id=rec["chat_id"],
            factory_revision=rec["factory_revision"] or "",
            schema_compat=rec["schema_compat"] or "",
            release_id=rec["release_id"] or "", actor=rec["actor"] or "",
            reason=rec["reason"] or "",
            source_updated_at=rec["source_updated_at"] or "",
            retired=bool(rec["retired"]), created_at=str(rec["created_at"]))

    def _revision_history_row(self, rec) -> HistoryRow:
        return HistoryRow(
            entry_type=ENTRY_REVISION, created_at=_norm_ts(rec["created_at"]),
            sort_id=str(rec["revision_id"]),
            revision_id=rec["revision_id"], origin=rec["origin"] or "",
            actor=rec["actor"] or "", scope=rec["scope"] or "global",
            chat_id=rec["chat_id"], retired=bool(rec["retired"]),
            schema_compat=rec["schema_compat"] or "",
            content_sha12=rec["content_sha12"] or "",
            chars=int(rec["char_count"] or 0), reason=rec["reason"] or "",
            release_id=rec["release_id"] or "",
            factory_revision=rec["factory_revision"] or "")

    def _activation_history_row(self, rec) -> HistoryRow:
        activation_id = int(rec["activation_id"] or 0)
        # §2.4 п.9 / §2.2 п.8: статус события — это статус ревизии, на которую
        # оно ссылается (снятая с регистрации/несовместимая версия не бывает
        # действием). Значения приходят из джойна страницы (или из стора).
        return HistoryRow(
            entry_type=ENTRY_ACTIVATION,
            created_at=_norm_ts(rec["created_at"]),
            sort_id=activation_sort_id(activation_id),
            revision_id=rec["revision_id"] or "", actor=rec["actor"] or "",
            scope=rec["scope"] or "global", chat_id=rec["chat_id"],
            retired=bool(rec["retired"]),
            schema_compat=rec["schema_compat"] or "",
            reason=rec["detail_code"] or "", release_id=rec["release_id"] or "",
            kind=rec["kind"] or "", outcome=rec["outcome"] or "",
            detail_code=rec["detail_code"] or "", activation_id=activation_id)

    async def list_history_page(self, block_id: str, *,
                               chat_id: int | None = None,
                               cursor: dict | None = None,
                               page_size: int = HISTORY_PAGE_DEFAULT
                               ) -> HistoryPage:
        """Страница объединённой истории (новые сверху) по keyset-курсору."""
        await self.ensure_journal()
        size = clamp_page_size(page_size)
        ts = _parse_ts(cursor["ts"]) if cursor else None
        sort_id = str((cursor or {}).get("sort_id") or "")

        async def _run(conn):
            revs = await conn.fetch(_PAGE_REVISIONS_DESC_SQL, block_id, chat_id,
                                    ts, sort_id, size + 1)
            acts = await conn.fetch(_PAGE_ACTIVATIONS_DESC_SQL, block_id,
                                    chat_id, ts, sort_id, size + 1)
            return revs, acts
        rev_recs, act_recs = await self._run_on_conn(_run)
        return _history_page_of(
            [self._revision_history_row(r) for r in rev_recs],
            [self._activation_history_row(a) for a in act_recs], cursor, size)

    async def list_revisions_page(self, block_id: str, *,
                                  chat_id: int | None = None,
                                  cursor: dict | None = None,
                                  page_size: int = HISTORY_PAGE_DEFAULT
                                  ) -> dict:
        """Ревизии страницей: первая страница — САМЫЕ НОВЫЕ, вглубь — старее.

        Внутри страницы порядок исторический (старые сверху), как в EVOL-017;
        курсор ведёт вглубь истории, поэтому свежая правка не прячется за
        первой сотней старых (§3.5 ТЗ).
        """
        await self.ensure_journal()
        size = clamp_page_size(page_size)
        ts = _parse_ts(cursor["ts"]) if cursor else None
        sort_id = str((cursor or {}).get("sort_id") or "")
        rank_start = int((cursor or {}).get("rank") or 1)

        async def _run(conn):
            return await conn.fetch(_PAGE_REVISIONS_DESC_SQL, block_id, chat_id,
                                    ts, sort_id, size + 1)
        recs = await self._run_on_conn(_run)
        rows = [self._revision_history_row(r) for r in recs]
        page = rows[:size]
        has_more = len(rows) > size
        next_cursor = (encode_history_cursor(page[-1].created_at,
                                             page[-1].sort_id,
                                             rank_start + len(page))
                       if has_more and page else "")
        return {"rows": list(reversed(page)), "next_cursor": next_cursor,
                "has_more": has_more, "rank_start": rank_start}

    async def list_activations_page(self, block_id: str, *,
                                    chat_id: int | None = None,
                                    cursor: dict | None = None,
                                    page_size: int = HISTORY_PAGE_DEFAULT
                                    ) -> dict:
        """События активаций страницей: новые сверху (контракт EVOL-017)."""
        await self.ensure_journal()
        size = clamp_page_size(page_size)
        ts = _parse_ts(cursor["ts"]) if cursor else None
        sort_id = str((cursor or {}).get("sort_id") or "")
        rank_start = int((cursor or {}).get("rank") or 1)

        async def _run(conn):
            return await conn.fetch(_PAGE_ACTIVATIONS_DESC_SQL, block_id,
                                    chat_id, ts, sort_id, size + 1)
        recs = await self._run_on_conn(_run)
        rows = [self._activation_history_row(r) for r in recs]
        page = rows[:size]
        has_more = len(rows) > size
        next_cursor = (encode_history_cursor(page[-1].created_at,
                                             page[-1].sort_id,
                                             rank_start + len(page))
                       if has_more and page else "")
        return {"rows": page, "next_cursor": next_cursor,
                "has_more": has_more, "rank_start": rank_start}

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


async def _record_legacy_snapshot(store, spec, *, scope: str,
                                  chat_id: int | None, current: str,
                                  cache, release_id: str,
                                  results: list) -> None:
    """Снимок действующих байтов scope как ``origin=legacy`` (§1.4, §3.7).

    Снимок делается ДО первой записи заводского текста: даже байты, равные
    заводским, подписываются ``origin=legacy`` (UI не выдаёт их за правку в
    админке); пустое значение → ``skipped_empty``, автор не выдумывается.

    Один и тот же снимок нужен двум веткам релиза: обычному cutover и
    закреплённому scope (owner baseline), который по ревью PVR-S2 N1 больше
    не идёт через cutover — иначе его ручной текст никогда не попадал бы в
    историю. Повторный вызов идемпотентен по ``revision_id``.
    """
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
        return
    await store.insert_activation(ActivationRow(
        block_id=spec.block_id, scope=scope, chat_id=chat_id,
        revision_id="", factory_revision_applied="",
        kind="legacy_import", outcome="skipped_empty",
        release_id=release_id, actor="", detail_code="legacy_empty"))
    results.append(BlockReleaseResult(
        spec.block_id, scope, chat_id, "legacy_snapshot",
        "skipped_empty", "legacy_import"))


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
    # §2.4 п.3: закреплённый владельцем scope (есть owner baseline) не
    # перетирается новой поставкой кода. Pin читается В ТОЙ ЖЕ транзакции
    # релиза — иначе план считался бы по устаревшему состоянию.
    baseline_event = await store.read_baseline_event(spec.block_id, scope,
                                                     chat_id)
    pinned = bool(baseline_event is not None
                  and baseline_event.kind == "baseline_assign"
                  and baseline_event.revision_id)
    plan = pr.activation_plan(
        code_label=code_label, sealed_sha=sealed_sha,
        text_sha12=pr.sha12(factory_body),
        applied_factory_revision=(state.factory_revision_applied
                                  if state is not None else ""),
        has_import=has_import, pinned=pinned)

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
    pinned_plan = plan.action == pr.PLAN_ACTIVATE_PINNED
    if state is not None and state.revision_id and current:
        drift = await _check_activation_drift(
            store, spec, scope, chat_id, state, current, release_id,
            activate_after=not pinned_plan)
        if drift is not None:
            results.append(drift)   # ERROR-аудит + снимок; активация ниже

    if current is None:
        current = ""

    if pinned_plan:
        # §2.4 п.3: у scope есть owner baseline. Новая заводская ревизия
        # пишется В ИСТОРИЮ, значение НЕ пишется, чатовый override не
        # снимается. Указатель применённой метки двигается (outcome
        # skipped_same) — следующий рестарт видит ту же метку и остаётся
        # истинным no-op, ``activation_drift`` не возникает.
        # РЕВЬЮ PVR-S2 N1: снимок текущих байтов не теряется и в этой ветке —
        # иначе scope без маркера импорта (ревизия пришла через
        # copy-to-global) навсегда оставался бы без legacy-снимка своего
        # ручного текста.
        if spec.pg_key and not has_import:
            await _record_legacy_snapshot(
                store, spec, scope=scope, chat_id=chat_id, current=current,
                cache=cache, release_id=release_id, results=results)
        revision = await _insert_revision_once(
            store, spec, origin="factory", body=factory_body, scope=scope,
            chat_id=chat_id, factory_revision=plan.code_revision,
            reason="factory_release_pinned", release_id=release_id)
        active_revision = state.revision_id if state is not None else ""
        await store.insert_activation(ActivationRow(
            block_id=spec.block_id, scope=scope, chat_id=chat_id,
            revision_id=active_revision,
            factory_revision_applied=plan.code_revision,
            kind="deploy_activate", outcome="skipped_same",
            release_id=release_id, actor="",
            detail_code="factory_superseded_pinned"))
        results.append(BlockReleaseResult(
            spec.block_id, scope, chat_id, plan.action, "skipped_same",
            "factory_superseded_pinned", revision_id=active_revision,
            factory_revision_applied=plan.code_revision))
        logger.info("[prompt_release] pinned scope: заводская ревизия %s "
                    "записана в историю, активный текст сохранён | block=%s | "
                    "scope=%s | chat=%s | baseline=%s", revision.revision_id,
                    spec.block_id, scope, chat_id,
                    baseline_event.revision_id if baseline_event else "")
        return

    if plan.action == pr.PLAN_LEGACY_CUTOVER and spec.pg_key:
        await _record_legacy_snapshot(
            store, spec, scope=scope, chat_id=chat_id, current=current,
            cache=cache, release_id=release_id, results=results)

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


def _revision_gate(revision, scope: str, chat_id: int | None) -> str:
    """Гейты ревизии для ЛЮБОГО действия с ней ("" — можно применять).

    Один порядок для активации, назначения baseline и восстановления:
    чужой scope/чат → ``retired`` → несовместимая ``schema_compat``. Такие
    ревизии читаются и сравниваются, но не активируются и не становятся
    рабочей базовой (§2.4 п.9).
    """
    foreign = _foreign_scope_reason(revision, scope, chat_id)
    if foreign:
        return foreign
    if getattr(revision, "retired", False):
        return "revision_retired"
    schema = str(getattr(revision, "schema_compat", "") or "")
    if schema and schema not in SUPPORTED_SCHEMA_COMPAT:
        return "schema_incompatible"
    return ""


async def activate_revision(block_id: str, revision_id: str, *, scope: str =
                            "global", chat_id: int | None = None,
                            actor=None, cache=None, store=None,
                            kind: str | None = None) -> dict:
    """Откат/вперёд: включить сохранённую совместимую ревизию (EVOL-017 API).

    Гейты: ревизия существует, не ``retired``, ``schema_compat`` совместим
    (пустой = совместим со всем), полномочия (hook). Несовместимая ревизия
    НЕ включается: ``applied=false, reason=schema_incompatible``, активный
    указатель не меняется, прежняя активная остаётся. История не удаляется;
    ``factory_revision_applied`` сохраняется — следующая НОВАЯ метка снова
    включает заводской текст (контракт §1.4).

    ``kind`` — вид события для ЯВНЫХ активаций эталона (§2.4 п.6–7:
    ``baseline_restore`` / ``factory_restore``). По умолчанию классификация
    откат/вперёд по порядку ревизий — прежнее поведение без изменений.
    """
    spec = pr.block(block_id)
    if spec is None or not spec.pg_key:
        return {"applied": False, "reason": "block_not_pg_managed",
                "block_id": block_id}
    if kind is not None and kind not in pr.ACTIVATION_KINDS:
        raise ValueError(f"неизвестный вид активации: {kind}")
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
    gate = _revision_gate(revision, scope, chat_id)
    if gate:
        logger.warning("[prompt_release] %s на попытке включения | block=%s | "
                       "revision=%s | revision_scope=%s/%s | requested=%s/%s",
                       gate, spec.block_id, revision_id, revision.scope,
                       revision.chat_id, scope, chat_id)
        result = {"applied": False, "reason": gate, "block_id": block_id,
                  "revision_id": revision_id}
        if gate == "revision_foreign_scope":
            result.update({"revision_scope": revision.scope,
                           "revision_chat_id": revision.chat_id})
        elif gate == "schema_incompatible":
            result["schema_compat"] = revision.schema_compat
        return result
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
            activation_kind = kind or "manual_rollback"
            if kind is None and state is not None and state.revision_id and \
                    state.revision_id != revision_id:
                # Детерминированный порядок (вставка ревизий в журнал), не
                # часы: цель создана раньше активной → откат; позже или
                # порядок неизвестен → возврат вперёд (EVOL-017).
                precedes = await store.revision_precedes(revision_id,
                                                         state.revision_id)
                activation_kind = ("manual_rollback" if precedes
                                   else "manual_forward")
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
                kind=activation_kind, outcome=outcome, release_id="",
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
                revision.revision_id, revision.origin, activation_kind,
                outcome, str(actor or ""))
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
            "activation_kind": activation_kind}


# ═══════════════════════════════════════════════════════════════════════════
# Owner baseline: указатель на существующую ревизию (контракт §2, §4)
# ═══════════════════════════════════════════════════════════════════════════

def _empty_baseline_payload(spec, scope: str,
                            chat_id: int | None) -> dict:
    """Состояние baseline без события: действует встроенная из кода (§4)."""
    return {"block_id": spec.block_id, "pg_key": spec.pg_key or "",
            "scope": scope, "chat_id": chat_id, "source": "factory",
            "baseline": None, "cleared_at": None, "cleared_by": ""}


async def _baseline_payload(store, spec, event: "BaselineEvent | None",
                            scope: str, chat_id: int | None) -> dict:
    """Человекочитаемое состояние baseline: указатель + провенанс ревизии.

    Тело текста сюда не входит (список/карточка не отдают тексты §3 п.7):
    ``sha256_12`` и длина достаточны для честного отображения, полный текст
    читается существующим ``get_revision_source``.
    """
    out = _empty_baseline_payload(spec, scope, chat_id)
    if event is None:
        return out
    if event.kind == "baseline_clear":
        # Явное снятие: действует встроенная из кода (§2.4 п.4).
        out["cleared_at"] = event.created_at
        out["cleared_by"] = event.actor
        return out
    revision = await store.get_revision(event.revision_id)
    active = await store.read_applied(spec.block_id, scope, chat_id)
    row: dict = {"revision_id": event.revision_id,
                 "assigned_at": event.created_at,
                 "assigned_by": event.actor,
                 "detail_code": event.detail_code,
                 "origin": (revision.origin if revision is not None else ""),
                 "available": revision is not None,
                 "is_active": bool(active is not None
                                   and active.revision_id == event.revision_id)}
    if revision is not None:
        row.update({
            "sha256_12": revision.content_sha12,
            "chars": _revision_chars(revision),
            "retired": bool(revision.retired),
            "schema_compat": revision.schema_compat or "",
            "compatible": _revision_gate(revision, scope, chat_id) == "",
            "factory_revision": revision.factory_revision or "",
            "created_at": revision.created_at,
        })
    out["baseline"] = row
    out["source"] = "owner"
    return out


async def _baseline_store(store, cache):
    """Стор журнала для baseline-операций (нет журнала → честный отказ)."""
    store = store if store is not None else default_journal(cache)
    if store is None:
        raise JournalUnavailable(
            "журнал версий недоступен: baseline не изменён")
    try:
        await store.ensure_journal()
    except Exception as exc:
        raise JournalUnavailable(
            f"журнал версий недоступен: {type(exc).__name__}") from exc
    return store


async def read_baseline(block_id: str, *, scope: str = "global",
                        chat_id: int | None = None, cache=None, store=None,
                        actor=None) -> dict:
    """Действующий owner baseline для (block_id, scope, chat_id) (§2.1).

    Читается ПОСЛЕДНЕЕ событие ``baseline_assign``/``baseline_clear``; тела
    текста не возвращаются. Журнал недоступен → :class:`JournalUnavailable`
    (HTTP 503), а не «baseline нет»: отсутствие события и недоступность
    журнала — разные факты.
    """
    spec = pr.block(block_id) or pr.by_pg_key(block_id)
    if spec is None:
        return {"known": False, "reason": "block_unknown",
                "block_id": block_id}
    scope = str(scope or "global")
    check_permission(str(actor or ""), "prompt.read_baseline",
                     block_id=spec.block_id, scope=scope, chat_id=chat_id)
    store = await _baseline_store(store, cache)
    try:
        event = await store.read_baseline_event(spec.block_id, scope, chat_id)
        out = await _baseline_payload(store, spec, event, scope, chat_id)
    except JournalUnavailable:
        raise
    except Exception as exc:
        logger.warning("[prompt_release] baseline недоступен", exc_info=True)
        raise JournalUnavailable(
            f"baseline read failed: {type(exc).__name__}") from exc
    out.update({"known": True, "journal_available": True,
                "factory_revision": pr.factory_revision(spec.block_id),
                "sealed_revision": pr.sealed_factory_revision(spec.block_id),
                "pg_managed": bool(spec.pg_key)})
    return out


async def assign_baseline(block_id: str, revision_id: str, *, scope: str =
                          "global", chat_id: int | None = None, actor=None,
                          cache=None, store=None, reason: str = "") -> dict:
    """«Назначить базовой»: только указатель, БЕЗ активации (§2.4 п.1).

    Дисциплина записи ровно как у :func:`activate_revision`: ``ensure_journal``
    → тот же advisory-лок ``prompt_release_apply`` → одна транзакция с
    ``SET LOCAL lock_timeout='5s'``; все чтения (ревизия, текущий baseline)
    внутри транзакции. Событие пишется с ``outcome='recorded'`` — «активная
    ревизия» и активный текст не двигаются, откат кода безопасен (§2.2).

    Повторное назначение уже назначенной ревизии идемпотентно: новой строки
    журнала не появляется (§2.4 п.2 ТЗ).
    """
    spec = pr.block(block_id) or pr.by_pg_key(block_id)
    if spec is None or not spec.pg_key:
        return {"applied": False, "reason": "block_not_pg_managed",
                "block_id": block_id}
    scope = str(scope or "global")
    if scope not in ("global", "chat"):
        return {"applied": False, "reason": "unknown_scope",
                "block_id": spec.block_id, "scope": scope}
    if scope == "chat" and chat_id is None:
        return {"applied": False, "reason": "chat_scope_requires_chat_id",
                "block_id": spec.block_id}
    check_permission(str(actor or ""), "prompt.assign_baseline",
                     block_id=spec.block_id, scope=scope, chat_id=chat_id)
    store = await _baseline_store(store, cache)
    revision = None
    async with store.apply_lock():
        async with store.transaction():
            revision = await store.get_revision(str(revision_id or ""))
            if revision is None or revision.block_id != spec.block_id:
                return {"applied": False, "reason": "revision_unknown",
                        "block_id": spec.block_id,
                        "revision_id": revision_id}
            gate = _revision_gate(revision, scope, chat_id)
            if gate:
                logger.warning("[prompt_release] %s на попытке назначения "
                               "базовой | block=%s | revision=%s",
                               gate, spec.block_id, revision_id)
                result = {"applied": False, "reason": gate,
                          "block_id": spec.block_id,
                          "revision_id": revision_id}
                if gate == "schema_incompatible":
                    result["schema_compat"] = revision.schema_compat
                if gate == "revision_foreign_scope":
                    result.update({"revision_scope": revision.scope,
                                   "revision_chat_id": revision.chat_id})
                return result
            current = await store.read_baseline_event(spec.block_id, scope,
                                                      chat_id)
            if (current is not None and current.kind == "baseline_assign"
                    and current.revision_id == revision.revision_id):
                payload = await _baseline_payload(store, spec, current, scope,
                                                  chat_id)
                return {"applied": False, "outcome": "skipped_same",
                        "reason": "baseline_same", "idempotent": True,
                        "revision_id": revision.revision_id,
                        "journal_recorded": True,
                        "active_text_changed": False,
                        "active_unchanged": True, "baseline": payload}
            state = await store.read_applied(spec.block_id, scope, chat_id)
            await store.insert_activation(ActivationRow(
                block_id=spec.block_id, scope=scope, chat_id=chat_id,
                revision_id=revision.revision_id,
                factory_revision_applied=(state.factory_revision_applied
                                          if state is not None else ""),
                kind="baseline_assign", outcome="recorded", release_id="",
                actor=str(actor or ""),
                detail_code=f"baseline:{revision.origin}"))
            event = await store.read_baseline_event(spec.block_id, scope,
                                                    chat_id)
            payload = await _baseline_payload(store, spec, event, scope,
                                              chat_id)
    logger.info("[prompt_release] baseline assigned | block=%s | scope=%s | "
                "chat=%s | rev=%s | origin=%s | actor=%s | reason=%s",
                spec.block_id, scope, chat_id, revision.revision_id,
                revision.origin, str(actor or ""), reason)
    return {"applied": True, "outcome": "recorded", "reason": "ok",
            "revision_id": revision.revision_id,
            "assigned_origin": revision.origin,
            "journal_recorded": True, "active_text_changed": False,
            "active_unchanged": True, "baseline": payload}


async def clear_baseline(block_id: str, *, scope: str = "global",
                         chat_id: int | None = None, actor=None, cache=None,
                         store=None, reason: str = "") -> dict:
    """«Снять назначение»: baseline снова — встроенная из кода (§2.4 п.4).

    Пишется ``baseline_clear`` (``revision_id=''``); активный текст НЕ
    меняется. После снятия действует обычная релизная политика: следующая
    новая заводская метка снова активирует заводской текст.
    """
    spec = pr.block(block_id) or pr.by_pg_key(block_id)
    if spec is None or not spec.pg_key:
        return {"applied": False, "reason": "block_not_pg_managed",
                "block_id": block_id}
    scope = str(scope or "global")
    if scope == "chat" and chat_id is None:
        return {"applied": False, "reason": "chat_scope_requires_chat_id",
                "block_id": spec.block_id}
    check_permission(str(actor or ""), "prompt.clear_baseline",
                     block_id=spec.block_id, scope=scope, chat_id=chat_id)
    store = await _baseline_store(store, cache)
    async with store.apply_lock():
        async with store.transaction():
            current = await store.read_baseline_event(spec.block_id, scope,
                                                      chat_id)
            if current is None or current.kind == "baseline_clear":
                return {"applied": False, "outcome": "skipped_same",
                        "reason": "baseline_absent", "idempotent": True,
                        "journal_recorded": True,
                        "active_text_changed": False,
                        "active_unchanged": True,
                        "baseline": _empty_baseline_payload(spec, scope,
                                                            chat_id)}
            state = await store.read_applied(spec.block_id, scope, chat_id)
            await store.insert_activation(ActivationRow(
                block_id=spec.block_id, scope=scope, chat_id=chat_id,
                revision_id="",
                factory_revision_applied=(state.factory_revision_applied
                                          if state is not None else ""),
                kind="baseline_clear", outcome="recorded", release_id="",
                actor=str(actor or ""), detail_code="baseline_clear"))
            event = await store.read_baseline_event(spec.block_id, scope,
                                                    chat_id)
            payload = await _baseline_payload(store, spec, event, scope,
                                              chat_id)
    logger.info("[prompt_release] baseline cleared | block=%s | scope=%s | "
                "chat=%s | actor=%s | reason=%s", spec.block_id, scope,
                chat_id, str(actor or ""), reason)
    return {"applied": True, "outcome": "recorded", "reason": "ok",
            "cleared_revision_id": (current.revision_id or ""),
            "journal_recorded": True, "active_text_changed": False,
            "active_unchanged": True, "baseline": payload}


async def restore_baseline(block_id: str, *, scope: str = "global",
                           chat_id: int | None = None, actor=None, cache=None,
                           store=None) -> dict:
    """«Восстановить базовую» — ЯВНАЯ активация эталона (§2.4 п.6).

    Тот же путь, что ручной откат: ``activate_revision`` (те же гейты
    ``retired``/``schema_compat``/чужой scope), вид события —
    ``baseline_restore``. Снятие чатового override — отдельная операция и
    здесь не выполняется (§7.3 п.7 ТЗ).
    """
    spec = pr.block(block_id) or pr.by_pg_key(block_id)
    if spec is None or not spec.pg_key:
        return {"applied": False, "reason": "block_not_pg_managed",
                "block_id": block_id}
    scope = str(scope or "global")
    store = await _baseline_store(store, cache)
    event = await store.read_baseline_event(spec.block_id, scope, chat_id)
    if (event is None or event.kind != "baseline_assign"
            or not event.revision_id):
        # Нет owner baseline: восстанавливать нечего, встроенная из кода
        # включается отдельным действием «Вернуть исходную из кода».
        return {"applied": False, "reason": "baseline_absent",
                "block_id": spec.block_id, "scope": scope,
                "chat_id": chat_id, "baseline_restore": True,
                "active_unchanged": True}
    result = await activate_revision(
        spec.block_id, event.revision_id, scope=scope, chat_id=chat_id,
        actor=actor, cache=cache, store=store, kind="baseline_restore")
    state_event = await store.read_baseline_event(spec.block_id, scope,
                                                  chat_id)
    result.update({"baseline_restore": True,
                   "restored_revision_id": event.revision_id,
                   "baseline": await _baseline_payload(
                       store, spec, state_event, scope, chat_id)})
    return result


async def restore_shipped_factory(block_id: str, *, scope: str = "global",
                                  chat_id: int | None = None, actor=None,
                                  cache=None, store=None,
                                  confirm: bool = False) -> dict:
    """«Вернуть исходную из кода» — подтверждённая активация (§2.4 п.7).

    Допускается только при ЦЕЛОЙ печати блока (``sha12(factory_text)`` равна
    подписи реестра); иначе ``factory_unverifiable`` и значение не меняется.
    Это активация (``kind='factory_restore'``); owner baseline НЕ снимается —
    снятие отдельным действием. ``origin`` ревизии никогда не переписывается:
    заводская ревизия берётся из ``factory_text``, ручная не переименовывается.
    """
    spec = pr.block(block_id) or pr.by_pg_key(block_id)
    if spec is None or not spec.pg_key:
        return {"applied": False, "reason": "block_not_pg_managed",
                "block_id": block_id}
    if confirm is not True:
        return {"applied": False, "reason": "confirmation_required",
                "block_id": spec.block_id, "scope": scope,
                "chat_id": chat_id, "active_unchanged": True}
    scope = str(scope or "global")
    check_permission(str(actor or ""), "prompt.restore_factory",
                     block_id=spec.block_id, scope=scope, chat_id=chat_id)
    seal_label, sealed_sha = (pr.FACTORY_REVISION_SEALS.get(spec.block_id)
                              or ("", ""))
    body = pr.factory_text(spec.block_id)
    if not seal_label or not sealed_sha or pr.sha12(body) != sealed_sha:
        logger.error("[prompt_release] factory_unverifiable | block=%s — "
                     "возврат к исходной из кода отклонён", spec.block_id)
        return {"applied": False, "reason": "factory_unverifiable",
                "block_id": spec.block_id, "scope": scope,
                "chat_id": chat_id, "active_unchanged": True}
    store = await _baseline_store(store, cache)
    revision_id = pr.revision_id_for(spec.block_id, scope, chat_id, "factory",
                                     pr.sha12(body))
    if await store.get_revision(revision_id) is None:
        # Заводская ревизия этой метки ещё не попадала в историю этого scope
        # (например, до cutover): пишем её ОДИН раз в той же дисциплине.
        async with store.apply_lock():
            async with store.transaction():
                if await store.get_revision(revision_id) is None:
                    await _insert_revision_once(
                        store, spec, origin="factory", body=body, scope=scope,
                        chat_id=chat_id,
                        factory_revision=pr.sealed_factory_revision(
                            spec.block_id),
                        reason="factory_restore", actor=str(actor or ""))
    result = await activate_revision(
        spec.block_id, revision_id, scope=scope, chat_id=chat_id, actor=actor,
        cache=cache, store=store, kind="factory_restore")
    state_event = await store.read_baseline_event(spec.block_id, scope,
                                                  chat_id)
    result.update({"factory_restore": True, "baseline_cleared": False,
                   "baseline": await _baseline_payload(
                       store, spec, state_event, scope, chat_id)})
    return result


async def copy_revision_to_global(block_id: str, revision_id: str, *,
                                  actor=None, cache=None, store=None,
                                  target_chat_id: int | None = None) -> dict:
    """«Скопировать как новую глобальную версию» (§2.4 п.8).

    Текст чужого scope переносится как НОВАЯ ревизия целевого (global) scope:
    ``origin='restored'``, ``reason='copied_from_chat:<revision_id>'``.
    ``revision_id`` источника не перепривязывается, его scope/чат не меняются,
    активный текст не меняется (копирование — не активация).
    """
    spec = pr.block(block_id) or pr.by_pg_key(block_id)
    if spec is None or not spec.pg_key:
        return {"applied": False, "reason": "block_not_pg_managed",
                "block_id": block_id}
    if target_chat_id is not None:
        return {"applied": False, "reason": "copy_target_is_global_only",
                "block_id": spec.block_id, "chat_id": target_chat_id}
    check_permission(str(actor or ""), "prompt.copy_to_global",
                     block_id=spec.block_id, revision_id=revision_id)
    store = await _baseline_store(store, cache)
    async with store.apply_lock():
        async with store.transaction():
            source = await store.get_revision(str(revision_id or ""))
            if source is None or source.block_id != spec.block_id:
                return {"applied": False, "reason": "revision_unknown",
                        "block_id": spec.block_id,
                        "revision_id": revision_id}
            if source.scope != "chat" or source.chat_id is None:
                return {"applied": False, "reason": "copy_source_not_chat",
                        "block_id": spec.block_id,
                        "revision_id": revision_id,
                        "revision_scope": source.scope}
            # §2.4 п.9: retired/несовместимую ревизию нельзя ни включить, ни
            # назначить, ни перенести в другой scope как рабочую версию —
            # провенанс (schema_compat) копируется как есть.
            gate = ""
            if source.retired:
                gate = "revision_retired"
            elif source.schema_compat and \
                    source.schema_compat not in SUPPORTED_SCHEMA_COMPAT:
                gate = "schema_incompatible"
            if gate:
                return {"applied": False, "reason": gate,
                        "block_id": spec.block_id,
                        "revision_id": revision_id}
            copy_reason = f"copied_from_chat:{source.revision_id}"
            target_id = pr.revision_id_for(spec.block_id, "global", None,
                                           "restored",
                                           pr.sha12(source.body or ""))
            created = await store.get_revision(target_id) is None
            row = await _insert_revision_once(
                store, spec, origin="restored", body=source.body or "",
                scope="global", chat_id=None, actor=str(actor or ""),
                reason=copy_reason, schema_compat=source.schema_compat or "")
            # РЕВЬЮ PVR-S2 N2: идентичность ревизии определяется байтами, а не
            # вызовом. Если те же байты уже копировали (из другого чата или
            # раньше), `ON CONFLICT DO NOTHING` оставляет ПРЕЖНЮЮ строку — и
            # ответ обязан отдавать фактически сохранённый `reason`, иначе
            # провенанс в ответе расходится с журналом.
            stored = await store.get_revision(row.revision_id)
            stored_reason = str((stored.reason if stored is not None
                                 else "") or "").strip()
            if stored_reason:
                copy_reason = stored_reason
    logger.info("[prompt_release] revision copied to global | block=%s | "
                "source=%s | chat=%s | new=%s | actor=%s", spec.block_id,
                source.revision_id, source.chat_id, row.revision_id,
                str(actor or ""))
    return {"applied": True, "reason": "ok", "created": created,
            "revision_id": row.revision_id,
            "source_revision_id": source.revision_id,
            "source_scope": source.scope, "source_chat_id": source.chat_id,
            "scope": "global", "chat_id": None, "origin": "restored",
            "sha256_12": row.content_sha12, "copy_reason": copy_reason,
            "journal_recorded": True, "active_text_changed": False,
            "active_unchanged": True}


async def list_versions(block_id: str, *, scope: str = "global",
                        chat_id: int | None = None, cache=None,
                        store=None, actor=None,
                        page_size: int = HISTORY_PAGE_DEFAULT,
                        cursor: str | None = None,
                        revisions_cursor: str | None = None,
                        activations_cursor: str | None = None) -> dict:
    """Данные «Истории версий» (EVOL-017): активная ревизия, заводская,
    хронология ревизий и событий включения. Тексты по умолчанию не отдаются
    (источник просмотра — ``get_revision_source``/``diff_revisions``).
    Ревью F4: доступ через hook полномочий (checker, иначе непустой actor).

    P0-2 (01.11.2026): сбой чтения журнала поднимает
    :class:`JournalUnavailable` (HTTP-слой отдаёт 503) — история не
    подменяется пустым списком.

    EPIC-PROMPT-VERSIONING-UX-01 §3.5 / §2.2 п.3 (PVR-S3): потолка истории
    больше нет. ``page_size`` — размер ОДНОЙ страницы (не лимит истории),
    ``cursor`` — непрозрачный keyset-курсор объединённой ленты ``entries``
    (новые сверху, курсор ведёт вглубь истории).
    ``revisions_cursor``/``activations_cursor`` листают исторические списки по
    отдельности: первая страница — самые новые записи, внутри страницы
    сохраняется прежний порядок (ревизии ASC, активации DESC).
    Тела текстов в списках отсутствуют всегда: ``body_available`` лишь
    сообщает, что полный текст можно запросить по ``revision_id``.
    """
    spec = pr.block(block_id)
    if spec is None:
        return {"block_id": block_id, "known": False}
    check_permission(str(actor or ""), "prompt.list_versions",
                     block_id=block_id, scope=scope, chat_id=chat_id)
    size = clamp_page_size(page_size)
    # Курсор разбирается ДО чтения журнала: испорченный курсор — это 422
    # запроса (ValueError), а не «журнал недоступен» (503).
    entries_cursor = decode_history_cursor(cursor)
    revs_cursor = decode_history_cursor(revisions_cursor)
    acts_cursor = decode_history_cursor(activations_cursor)
    store = store if store is not None else default_journal(cache)
    entries = HistoryPage(rows=[])
    revisions_page: dict = {"rows": [], "next_cursor": "", "has_more": False,
                           "rank_start": 1}
    activations_page: dict = {"rows": [], "next_cursor": "", "has_more": False,
                             "rank_start": 1}
    state = None
    baseline_event = None
    if store is not None:
        try:
            await store.ensure_journal()
            entries = await store.list_history_page(
                block_id, chat_id=chat_id, cursor=entries_cursor,
                page_size=size)
            revisions_page = await store.list_revisions_page(
                block_id, chat_id=chat_id, cursor=revs_cursor,
                page_size=size)
            activations_page = await store.list_activations_page(
                block_id, chat_id=chat_id, cursor=acts_cursor,
                page_size=size)
            state = await store.read_applied(spec.block_id, scope, chat_id)
            baseline_event = await store.read_baseline_event(
                spec.block_id, scope, chat_id)
        except Exception as exc:
            # Ревью P0-2 (01.11.2026): раньше сбой чтения журнала глотался и
            # отдавался ПУСТОЙ список — история выглядела «пустой», хотя она
            # есть (запрещено скрывать отказ под пустым массивом). Теперь
            # вызывающий получает честный JournalUnavailable (HTTP 503).
            logger.warning("[prompt_release] список ревизий недоступен",
                           exc_info=True)
            raise JournalUnavailable(
                f"journal read failed: {type(exc).__name__}") from exc
    active_id = str(state.revision_id or "") if state is not None else ""
    baseline_id = (str(baseline_event.revision_id or "")
                   if baseline_event is not None
                   and baseline_event.kind == "baseline_assign" else "")
    active = None
    if state is not None and state.revision_id:
        rev = await store.get_revision(state.revision_id)
        if rev is not None:
            active = {"revision_id": rev.revision_id, "origin": rev.origin,
                      "sha256_12": rev.content_sha12,
                      "chars": len(rev.body or ""),
                      "created_at": rev.created_at,
                      "source": history_source(rev.origin),
                      "factory_revision_applied":
                          state.factory_revision_applied}

    def _entry(row, order: int) -> dict:
        status = _status_of_row(row, active_id, baseline_id)
        source = history_source(row.origin, kind=row.kind)
        return {
            "entry_type": row.entry_type,
            "order": int(order),
            "created_at": row.created_at,
            "revision_id": row.revision_id,
            "event_id": row.activation_id or None,
            "source": source,
            "source_label": history_source_label(source, kind=row.kind),
            "origin": row.origin or "",
            "kind": row.kind or "",
            "outcome": row.outcome or "",
            "detail_code": row.detail_code or "",
            "actor": row.actor,
            "scope": row.scope,
            "chat_id": row.chat_id,
            "status": status,
            "status_label": history_status_label(status),
            # §2.4 п.9/§2.2 п.8: retired и несовместимые читаются и
            # сравниваются, но действие над ними недоступно всегда.
            "actionable": status not in ("retired", "incompatible"),
            "reason": row.reason or "",
            "reason_text": history_reason_text(
                status, schema_compat=row.schema_compat,
                detail_code=row.detail_code),
            # Тело в списке не отдаётся никогда: флаг говорит лишь о том, что
            # его можно запросить по revision_id (§3.7 ТЗ).
            "body_available": bool(row.entry_type == ENTRY_REVISION
                                   or row.revision_id),
            "chars": int(row.chars or 0),
            "sha256_12": row.content_sha12,
            "release_id": row.release_id,
            "factory_revision": row.factory_revision,
            "schema_compat": row.schema_compat,
            "retired": bool(row.retired),
        }

    rows: list[dict] = []
    for r in revisions_page["rows"]:
        item = _entry(r, 0)
        item.pop("order", None)
        item.pop("entry_type", None)
        item.pop("event_id", None)
        item.pop("kind", None)
        item.pop("outcome", None)
        item.pop("detail_code", None)
        item["chars"] = int(r.chars or 0)
        rows.append(item)
    events: list[dict] = []
    for a in activations_page["rows"]:
        status = _status_of_row(a, active_id, baseline_id)
        source = history_source(a.origin, kind=a.kind)
        events.append({
            "kind": a.kind, "outcome": a.outcome,
            "revision_id": a.revision_id, "scope": a.scope,
            "chat_id": a.chat_id, "release_id": a.release_id,
            "actor": a.actor, "detail_code": a.detail_code,
            "created_at": a.created_at,
            "activation_id": a.activation_id or None,
            "source": source, "source_label": history_source_label(source,
                                                                    kind=a.kind),
            "status": status, "status_label": history_status_label(status),
            "actionable": status not in ("retired", "incompatible"),
            "reason_text": history_reason_text(
                status, schema_compat=a.schema_compat,
                detail_code=a.detail_code),
            "body_available": bool(a.revision_id),
        })
    # §2.4: owner baseline — часть состояния «Истории версий» того же ответа
    # (UI не делает второй запрос). Нет журнала — baseline честно не известен.
    baseline = _empty_baseline_payload(spec, scope, chat_id)
    if store is not None:
        try:
            baseline = await _baseline_payload(store, spec, baseline_event,
                                               scope, chat_id)
        except Exception:      # pragma: no cover — baseline не рушит историю
            logger.warning("[prompt_release] baseline недоступен в истории",
                           exc_info=True)
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
        "baseline": baseline,
        # Объединённая лента «сохранения + активации» — основной список панели
        # истории (§2.2 п.3), новые сверху, один стабильный курсор.
        "entries": [_entry(row, entries.rank_start + idx)
                    for idx, row in enumerate(entries.rows)],
        "page": {
            "page_size": size,
            "order": HISTORY_ORDER_NEWEST,
            "next_cursor": entries.next_cursor,
            "has_more": bool(entries.has_more),
            "returned": len(entries.rows),
            "rank_start": int(entries.rank_start),
            "total_known": None,        # честно: полный COUNT страницей не нужен
        },
        "revisions": rows,
        "revisions_page": {
            # Внутри страницы — исторический порядок; первая страница содержит
            # самые НОВЫЕ ревизии, курсор ведёт вглубь (старее).
            "order": HISTORY_ORDER_OLDEST,
            "paging": HISTORY_ORDER_NEWEST,
            "next_cursor": revisions_page["next_cursor"],
            "has_more": bool(revisions_page["has_more"]),
            "returned": len(rows),
        },
        "activations": events,
        "activations_page": {
            "order": HISTORY_ORDER_NEWEST,
            "next_cursor": activations_page["next_cursor"],
            "has_more": bool(activations_page["has_more"]),
            "returned": len(events),
        },
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

    Ревью F4: доступ через hook полномочий; тела промптов в логи не пишутся.
    PVR-S3 (§2.2 п.4, §2.4 п.9): тело доступно всегда, даже у ``retired`` и
    несовместимой ревизии — «недоступно» не подменяется пустым текстом, а
    причина и запрет действия отдаются явно (``status``/``reason_text``/
    ``actionable``).
    """
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
    status = history_status(retired=bool(revision.retired),
                            schema_compat=str(revision.schema_compat or ""),
                            revision_id=revision.revision_id)
    source = history_source(revision.origin)
    return {"known": True, "revision_id": revision.revision_id,
            "block_id": revision.block_id, "origin": revision.origin,
            "sha256_12": revision.content_sha12, "body": revision.body,
            "created_at": revision.created_at, "retired": revision.retired,
            "schema_compat": revision.schema_compat,
            "scope": revision.scope, "chat_id": revision.chat_id,
            "actor": revision.actor, "reason": revision.reason,
            "chars": len(revision.body or ""),
            "source": source, "source_label": history_source_label(source),
            "status": status, "status_label": history_status_label(status),
            "actionable": status not in ("retired", "incompatible"),
            "reason_text": history_reason_text(
                status, schema_compat=revision.schema_compat),
            # Список тел не отдаёт; здесь тело есть — флаг нужен UI, чтобы
            # различить «текст доступен» и «текст исторически утрачен».
            "body_available": True}


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
                                 and not x.startswith("---")),
            # §2.2 п.5/§2.4 п.9: retired и несовместимые ревизии сравниваются
            # как обычные — но причина запрета действия остаётся видимой.
            "statuses": {"a": a.get("status", ""), "b": b.get("status", "")},
            "reason_text": (a.get("reason_text") or b.get("reason_text") or ""),
            "actionable": bool(a.get("actionable") and b.get("actionable"))}


__all__ = [
    "CUTOVER_RELEASE_ID", "JOURNAL_DDL", "SUPPORTED_SCHEMA_COMPAT",
    "LOCK_TIMEOUT_SQL", "NON_TEXT_VALUE_KEYS",
    "HISTORY_PAGE_DEFAULT", "HISTORY_PAGE_MAX", "HISTORY_ORDER_NEWEST",
    "HISTORY_ORDER_OLDEST", "REVISION_SOURCES", "REVISION_STATUSES",
    "HistoryRow", "HistoryPage", "clamp_page_size", "encode_history_cursor",
    "decode_history_cursor", "activation_sort_id", "history_source",
    "history_source_label", "history_status", "history_status_label",
    "history_reason_text",
    "RevisionRow", "ActivationRow", "AppliedState", "BaselineEvent",
    "BlockReleaseResult",
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
    "read_baseline", "assign_baseline", "clear_baseline",
    "restore_baseline", "restore_shipped_factory", "copy_revision_to_global",
]
