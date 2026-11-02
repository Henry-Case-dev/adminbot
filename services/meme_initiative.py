"""EVOL-014 — инициативные мемы: capability внутри цикла Initiative.

Это не замена инициативы и не отдельный cron. Решение «пробовать ли мем»
принимает существующий проход ``initiative.observe``; здесь живёт только
способность собрать выжимку одного чата и заказать картинку.

MEME-PIPELINE-REFactor-01 (03.11.2026): пайплайн внутри ЭТОГО же сервиса
состоит из трёх явных этапов — выжимка → прикол → картинка. Второй
параллельной ветки нет.

Инварианты:
  * свой тумблер, заводской OFF; выключение мемов не трогает текстовую
    инициативу; выключение Initiative останавливает и мемы;
  * триггер — только санкционированный контур ``mca_random_source``
    (purpose ``meme_trigger``). Недоступность контура → ``random_unavailable``.
    Локального ``random`` / Math.random нет;
  * окно сообщений и cooldown конфигурируются (дефолт окна 500 — не кап);
  * этап A (выжимка) потолком длины НЕ ограничен: суммаризатор получает окно
    и системный промпт, никакой цели в символах и постфактум-обрезки;
  * этап B (прикол) — обязательный отдельный LLM-вызов по выжимке; длина
    ограничивается здесь: ``J = max(0, L - T)`` уходит модели явной
    инструкцией, защитная обрезка — только страховка от перелёта;
  * этап C (картинка) собирает итоговый prompt из шаблона и ПРИКОЛА
    (не из сырой выжимки); потолок L относится именно к этому тексту;
  * ``manual=True`` (диагностика ``/meme``) обходит квоту/кулдаун/минимум
    сообщений/случайный триггер/тихие часы/in-flight/гейт публикации, но НЕ
    права, готовность image-модуля, наличие журнала и разрешимость бюджета;
  * заводской image-prompt — дословный префикс ``Создай мем с шрифтом импакт:``
    плюс прикол; текст берётся из реестра промптов;
  * суточная квота — свой счётчик (не ``image_calls``): бронь до вызова
    провайдера, день — календарный в TZ чата (нет TZ → UTC с пометкой
    fallback). Нет таблицы → честный ``schema_absent``, без генерации;
  * публикация следует publish/recheck-гейту. Гейт закрыт → картинка не
    уходит в чат, причина пишется. Живых отправок из тестов нет.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# ── заводские промпты (реестр: declare_prompt + печать) ─────────────────────
#: Дословно, слово в слово. Шаблон этапа C: прикол подставляется на ``{joke}``,
#: а если плейсхолдера нет — дописывается в хвост (историческое поведение).
MEME_IMAGE_PROMPT = "Создай мем с шрифтом импакт:"

#: Дословно (владелец, §1–§2 ТЗ). Промпт этапа B.
MEME_JOKE_PROMPT = "Придумай короткий абсурдный прикол из этой выжимки."

#: Лёгкая инструкция выжимки. Потолка в символах здесь нет и быть не должно:
#: этап A больше не ограничивается длиной (§1 ТЗ, «потолок снят с выжимки»).
MEME_SUMMARY_SYSTEM_PROMPT = (
    "Собери короткую выжимку именно под мем из сообщений одного чата. "
    "Нужен мемный хук: конфликт, шутка, повтор, абсурд или локальный инсайд, "
    "а не пересказ разговора вообще. Не добавляй фактов, которых нет в окне, "
    "и сохрани конкретику (кто, что, над чем шутка). Верни только текст "
    "выжимки, без кавычек, заголовков и пояснений."
)

#: Плейсхолдер прикола в шаблоне картинки. Больше одного — ошибка конфигурации.
JOKE_PLACEHOLDER = "{joke}"

#: Инструкция длины дописывается ПОСЛЕ редактируемого промпта этапа B: правка
#: промпта в админке не отменяет автоматический потолок (§3 ТЗ).
JOKE_LENGTH_DIRECTIVE = ("Сгенерируй прикол длиной не более {n} символов. "
                         "Верни только текст прикола.")

IMAGE_PROMPT_BLOCK_ID = "initiative.meme.image"
SUMMARY_PROMPT_BLOCK_ID = "initiative.meme.summary"
JOKE_PROMPT_BLOCK_ID = "initiative.meme.joke"

OUTPUT_KIND = "meme_initiative"

# ── настройки (дефолты; override чата → hot → дефолт; не магические капы) ──
KEY_ENABLED = "flags.meme_initiative_enabled"
KEY_WINDOW = "initiative.meme_window_messages"
KEY_DAILY_LIMIT = "initiative.meme_daily_limit"
KEY_COOLDOWN = "initiative.meme_cooldown_seconds"
KEY_MIN_MESSAGES = "initiative.meme_min_messages"
KEY_PROBABILITY = "initiative.meme_trigger_probability"
KEY_LENGTH_ADMIN = "initiative.meme_length_limit"
KEY_LENGTH_OVERRIDE = "initiative.meme_length_override"
KEY_SUMMARIZER_MODEL = "initiative.meme_summarizer_model"
KEY_QUIET_HOURS = "initiative.meme_quiet_hours"

DEFAULT_ENABLED = False
DEFAULT_WINDOW_MESSAGES = 500
DEFAULT_DAILY_LIMIT = 3
DEFAULT_COOLDOWN_SECONDS = 6 * 3600
DEFAULT_MIN_MESSAGES = 8
DEFAULT_TRIGGER_PROBABILITY = 0.05
IN_FLIGHT_STALE_SECONDS = 900

# ── таксономия skip (отдельно от общих кодов инициативы) ────────────────────
SKIP_DISABLED = "disabled_by_setting"
SKIP_INITIATIVE_DISABLED = "initiative_disabled"
SKIP_IMAGE_MODULE_OFF = "image_module_off"
SKIP_IMAGE_NOT_CONFIGURED = "image_provider_not_configured"
SKIP_IMAGE_UNHEALTHY = "image_provider_unhealthy"
SKIP_RANDOM_UNAVAILABLE = "random_unavailable"
SKIP_RANDOM_MISS = "no_random_hit"
SKIP_COOLDOWN = "cooldown_active"
SKIP_SUMMARY = "summary_failed"
#: Этап B: отдельные коды — «прикол не сгенерился» не равно «выжимка упала».
SKIP_JOKE_FAILED = "joke_generation_failed"
SKIP_JOKE_EMPTY = "joke_empty"
SKIP_NO_JOKE_BUDGET = "no_joke_budget"
SKIP_TEMPLATE_EMPTY = "template_empty"
SKIP_IMAGE_FAILED = "image_generation_failed"
SKIP_PUBLISH = "publish_blocked"
SKIP_QUOTA = "daily_quota_reached"
SKIP_ACTIVITY = "low_activity"
SKIP_SCHEMA = "schema_absent"
SKIP_LENGTH_UNKNOWN = "length_limit_unknown"
SKIP_IN_FLIGHT = "in_flight"
SKIP_QUIET = "quiet_hours"
#: Мост «цикл инициативы → мем» сломался. Это НЕ провал выжимки: выжимка
#: могла вообще не вызываться. Отдельный код, чтобы аналитика не врала.
SKIP_CYCLE_EXCEPTION = "cycle_exception"
#: Retry уже снятой брони (вызов провайдера достоверно не начинался).
SKIP_SLOT_RELEASED = "slot_released"
#: INIT-COORD (03.11.2026): координация публикаций двух механизмов.
SKIP_PUBLICATION_CONFLICT = "publication_conflict"
SKIP_PUBLICATION_IN_FLIGHT = "publication_in_flight"
SKIP_PUBLICATION_STALE = "publication_stale"
SKIP_PUBLICATION_EXPIRED = "publication_expired"

SKIP_REASONS = (
    SKIP_DISABLED, SKIP_INITIATIVE_DISABLED, SKIP_IMAGE_MODULE_OFF,
    SKIP_IMAGE_NOT_CONFIGURED, SKIP_IMAGE_UNHEALTHY, SKIP_RANDOM_UNAVAILABLE,
    SKIP_RANDOM_MISS, SKIP_COOLDOWN, SKIP_SUMMARY, SKIP_JOKE_FAILED,
    SKIP_JOKE_EMPTY, SKIP_NO_JOKE_BUDGET, SKIP_TEMPLATE_EMPTY,
    SKIP_IMAGE_FAILED, SKIP_PUBLISH, SKIP_QUOTA, SKIP_ACTIVITY, SKIP_SCHEMA,
    SKIP_LENGTH_UNKNOWN, SKIP_IN_FLIGHT, SKIP_QUIET, SKIP_CYCLE_EXCEPTION,
    SKIP_SLOT_RELEASED, SKIP_PUBLICATION_CONFLICT,
    SKIP_PUBLICATION_IN_FLIGHT, SKIP_PUBLICATION_STALE,
    SKIP_PUBLICATION_EXPIRED,
)

STAGE_CONSIDERED = "considered"
STAGE_ELIGIBLE = "eligible"
STAGE_SUMMARY = "summary"
#: MEME-PIPELINE-REFactor-01: обязательный этап B между выжимкой и картинкой.
STAGE_JOKE = "joke"
STAGE_IMAGE = "image_generation"
STAGE_PUBLISH = "publish"
STAGE_FAILED = "failed"
STAGE_SKIPPED = "skipped"
STAGES = (
    STAGE_CONSIDERED, STAGE_ELIGIBLE, STAGE_SUMMARY, STAGE_JOKE, STAGE_IMAGE,
    STAGE_PUBLISH, STAGE_FAILED, STAGE_SKIPPED,
)

COUNTED_STATUSES = ("reserved", "provider_called", "provider_failed")
SCHEMA_VERSION_TARGET = 40
#: Имя шага в книге `schema_migrations` (services/database.py, v40).
SCHEMA_MIGRATION_STEP_NAME = "meme_quota_journal_v40"
RESERVATION_TABLE = "meme_initiative_reservation"
ATTEMPT_TABLE = "meme_initiative_attempt"

SCHEMA_DDL_SQLITE = (
    f"CREATE TABLE IF NOT EXISTS {RESERVATION_TABLE} ("
    "job_id TEXT PRIMARY KEY,"
    "chat_id INTEGER NOT NULL,"
    "day_bucket TEXT NOT NULL,"
    "timezone_name TEXT NOT NULL,"
    "timezone_source TEXT NOT NULL,"
    "status TEXT NOT NULL,"
    "error_code TEXT NOT NULL DEFAULT '',"
    "created_at INTEGER NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_meme_reservation_chat_day "
    f"ON {RESERVATION_TABLE} (chat_id, day_bucket, status)",
    f"CREATE TABLE IF NOT EXISTS {ATTEMPT_TABLE} ("
    "attempt_id TEXT PRIMARY KEY,"
    "chat_id INTEGER NOT NULL,"
    "job_id TEXT NOT NULL DEFAULT '',"
    "ts INTEGER NOT NULL,"
    "stage TEXT NOT NULL,"
    "outcome TEXT NOT NULL,"
    "reason_code TEXT NOT NULL DEFAULT '',"
    "detail TEXT NOT NULL DEFAULT '',"
    "limit_source TEXT NOT NULL DEFAULT '',"
    "limit_value INTEGER,"
    "window_messages INTEGER)",
    "CREATE INDEX IF NOT EXISTS idx_meme_attempt_chat_ts "
    f"ON {ATTEMPT_TABLE} (chat_id, ts)",
)

#: Справочный набор для PostgreSQL — НЕ зарегистрирован и НЕ применяется.
#: Журнала квоты на PG нет: `SqliteQuotaLedger` работает с файлом SQLite, а
#: `pg_db.DDL_STATEMENTS` этих таблиц не содержит намеренно (пустые PG-таблицы
#: никто не читает, и они выдавали бы несуществующую поддержку PG). Набор
#: оставлен как форма контракта для будущего PG-журнала; пока он не подключён,
#: `schema_absent` на PG-контуре честен.
SCHEMA_DDL_POSTGRES = (
    f"CREATE TABLE IF NOT EXISTS {RESERVATION_TABLE} ("
    "job_id TEXT PRIMARY KEY,"
    "chat_id BIGINT NOT NULL,"
    "day_bucket TEXT NOT NULL,"
    "timezone_name TEXT NOT NULL,"
    "timezone_source TEXT NOT NULL,"
    "status TEXT NOT NULL,"
    "error_code TEXT NOT NULL DEFAULT '',"
    "created_at BIGINT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_meme_reservation_chat_day "
    f"ON {RESERVATION_TABLE} (chat_id, day_bucket, status)",
    f"CREATE TABLE IF NOT EXISTS {ATTEMPT_TABLE} ("
    "attempt_id TEXT PRIMARY KEY,"
    "chat_id BIGINT NOT NULL,"
    "job_id TEXT NOT NULL DEFAULT '',"
    "ts BIGINT NOT NULL,"
    "stage TEXT NOT NULL,"
    "outcome TEXT NOT NULL,"
    "reason_code TEXT NOT NULL DEFAULT '',"
    "detail TEXT NOT NULL DEFAULT '',"
    "limit_source TEXT NOT NULL DEFAULT '',"
    "limit_value INTEGER,"
    "window_messages INTEGER)",
    "CREATE INDEX IF NOT EXISTS idx_meme_attempt_chat_ts "
    f"ON {ATTEMPT_TABLE} (chat_id, ts)",
)

WINDOW_SQL = (
    "SELECT id, chat_id, text FROM smart_messages "
    "WHERE chat_id = ? AND import_key IS NULL "
    "ORDER BY id DESC LIMIT ?"
)

_PROCESS_ATTEMPTS: deque = deque(maxlen=200)


def reset_process_attempts() -> None:
    """Сброс процессного кольца попыток (тесты). Квоту не трогает."""
    _PROCESS_ATTEMPTS.clear()


def sqlite_path_of(db) -> str | None:
    """Путь файла SQLite у DatabaseService или соединения. Нет пути → None."""
    path = getattr(db, "db_path", None) or getattr(db, "path", None)
    if not path:
        raw = getattr(db, "db", None)
        path = getattr(raw, "path", None) if raw is not None else None
    if not path:
        return None
    text = str(path)
    if text in ("", ":memory:"):
        return None
    return text


def open_ledger(db) -> SqliteQuotaLedger | None:
    """Журнал, если таблица уже есть. Не создаёт схему."""
    path = sqlite_path_of(db)
    if not path:
        return None
    ledger = SqliteQuotaLedger(path)
    try:
        if not ledger.table_present():
            return None
    except Exception:
        return None
    return ledger


def blocks_text_initiative() -> bool:
    """Мемы никогда не отключают текстовые инициативные реплики."""
    return False


# ── свой ростер чатов (INIT-COORD §1, V1) ──────────────────────────────────
#: Предел сканирования кандидатов (граница чтения, не «лимит попыток»: сама
#: попытка за проход ограничена существующей ``MAX_CHATS_PER_PASS``).
ROSTER_SCAN_MAX = 32


async def _candidate_chat_ids(db) -> list[int]:
    """Чаты, где вообще есть переписка: PG `chat_profiles` либо SQLite.

    PG — прецедент `summary_scheduler` (durable список профилей чатов);
    любой сбой PG → durable SQLite-список `smart_messages`, а не пустой
    ростер: недоступность одного источника не должна выключать механизм.
    """
    try:
        from services import pg_db
        pool = getattr(pg_db, "pool", None)
        if pool is not None:
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT chat_id FROM chat_profiles")
            ids = [int(row["chat_id"]) for row in rows or ()
                   if row["chat_id"] is not None]
            if ids:
                return ids
    except Exception:
        logger.debug("[meme] pg chat roster unavailable", exc_info=True)
    get_ids = getattr(db, "get_smart_chat_ids", None)
    if get_ids is None:
        raise RuntimeError("chat_roster_unavailable")
    return [int(chat_id) for chat_id in (await get_ids()) or ()]


async def meme_chat_roster(db, *, state: dict | None = None,
                           limit: int | None = None) -> list[int]:
    """СВОЙ список чатов мема: не производная от текстового скана.

    Порядок отбора (INIT-COORD §1): все групповые чаты с перепиской → гейт
    чата ``initiative.enabled`` (``chat_observer_enabled``) → тумблер мемов
    чата. Тихий чат без новых сообщений в ростер попадает: планирование мемов
    не зависит от того, что увидел текстовый сканер. За проход берётся не
    больше ``MAX_CHATS_PER_PASS`` чатов, начиная с тех, кого дольше не
    проверяли (``state`` — durable per-chat состояние payload), чтобы
    маленький лимит не морил один и тот же чат.
    """
    from services.initiative_observer import MAX_CHATS_PER_PASS, \
        chat_observer_enabled

    cap = int(limit if limit is not None else MAX_CHATS_PER_PASS)
    cap = max(1, cap)
    ids = await _candidate_chat_ids(db)
    candidates: list[int] = []
    for chat_id in ids:
        if int(chat_id) >= 0:            # инициатива работает в группах
            continue
        if int(chat_id) not in candidates:
            candidates.append(int(chat_id))
    candidates = candidates[:ROSTER_SCAN_MAX]
    enabled: list[int] = []
    for chat_id in candidates:
        try:
            if not await chat_observer_enabled(int(chat_id)):
                continue
        except Exception:
            continue
        try:
            cfg = await load_settings(int(chat_id))
        except Exception:
            continue
        if not cfg.enabled:
            continue
        enabled.append(int(chat_id))
    buckets = state if isinstance(state, dict) else {}

    def _last(chat_id: int) -> int:
        entry = buckets.get(str(int(chat_id)))
        if not isinstance(entry, dict):
            return 0
        try:
            return int(entry.get("last_check_ts") or 0)
        except (TypeError, ValueError):
            return 0

    enabled.sort(key=lambda cid: (_last(cid), -int(cid)))
    return enabled[:cap]


def schema_integration_note() -> str:
    """Состояние шага схемы v40 (уже зарегистрирован, не «будущий»)."""
    return (
        f"v{SCHEMA_VERSION_TARGET}: аддитивные таблицы {RESERVATION_TABLE} и "
        f"{ATTEMPT_TABLE}. Шаг зарегистрирован в services/database.py "
        f"(_migrate_meme_quota_v40, имя в книге схемы — "
        f"{SCHEMA_MIGRATION_STEP_NAME}) и применяет модульный DDL "
        "через CREATE TABLE/INDEX IF NOT EXISTS, поэтому повтор и рестарт — "
        "no-op. Если таблицы нет, значит миграция не применилась на этой БД: "
        "это честный schema_absent (без вызова image-провайдера и без "
        "авто-CREATE на горячем пути), а не штатный режим. DDL: "
        "SCHEMA_DDL_SQLITE; PG-копии нет — журнал квоты SQLite-only."
    )


# ── настройки ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MemeSettings:
    enabled: bool = DEFAULT_ENABLED
    window_messages: int = DEFAULT_WINDOW_MESSAGES
    daily_limit: int = DEFAULT_DAILY_LIMIT
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS
    min_messages: int = DEFAULT_MIN_MESSAGES
    trigger_probability: float = DEFAULT_TRIGGER_PROBABILITY
    length_admin: int | None = None
    length_override: int | None = None
    summarizer_model: str = ""
    quiet_hours: str = ""

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "window_messages": self.window_messages,
            "daily_limit": self.daily_limit,
            "cooldown_seconds": self.cooldown_seconds,
            "min_messages": self.min_messages,
            "trigger_probability": self.trigger_probability,
            "length_admin": self.length_admin,
            "length_override": self.length_override,
            "summarizer_model": self.summarizer_model,
            "quiet_hours": self.quiet_hours,
        }


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if value is None:
        return default
    return bool(value)


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


async def _param(chat_id: int | None, key: str, default):
    try:
        if chat_id is not None:
            from services import chat_params
            value = await chat_params.get_chat_param(int(chat_id), key, default)
            if value is not None:
                return value
        from services import hot_config as hot
        value = hot.get(key, default)
        return default if value is None else value
    except Exception:
        return default


async def load_settings(chat_id: int | None) -> MemeSettings:
    enabled = _as_bool(await _param(chat_id, KEY_ENABLED, DEFAULT_ENABLED),
                       DEFAULT_ENABLED)
    window = max(1, _as_int(await _param(chat_id, KEY_WINDOW,
                                         DEFAULT_WINDOW_MESSAGES),
                            DEFAULT_WINDOW_MESSAGES))
    limit = _as_int(await _param(chat_id, KEY_DAILY_LIMIT, DEFAULT_DAILY_LIMIT),
                    DEFAULT_DAILY_LIMIT)
    if limit < 0:
        limit = 0
    cooldown = max(0, _as_int(await _param(chat_id, KEY_COOLDOWN,
                                           DEFAULT_COOLDOWN_SECONDS),
                              DEFAULT_COOLDOWN_SECONDS))
    minimum = max(0, _as_int(await _param(chat_id, KEY_MIN_MESSAGES,
                                          DEFAULT_MIN_MESSAGES),
                             DEFAULT_MIN_MESSAGES))
    try:
        probability = float(await _param(chat_id, KEY_PROBABILITY,
                                         DEFAULT_TRIGGER_PROBABILITY))
    except (TypeError, ValueError):
        probability = DEFAULT_TRIGGER_PROBABILITY
    probability = min(1.0, max(0.0, probability))
    quiet = str(await _param(chat_id, KEY_QUIET_HOURS, "") or "")
    model = str(await _param(chat_id, KEY_SUMMARIZER_MODEL, "") or "")
    return MemeSettings(
        enabled=enabled,
        window_messages=window,
        daily_limit=limit,
        cooldown_seconds=cooldown,
        min_messages=minimum,
        trigger_probability=probability,
        length_admin=_optional_int(await _param(chat_id, KEY_LENGTH_ADMIN, None)),
        length_override=_optional_int(
            await _param(chat_id, KEY_LENGTH_OVERRIDE, None)),
        summarizer_model=model,
        quiet_hours=quiet.strip(),
    )


# ── бюджет длины: L (итоговый prompt), T (шаблон), J = max(0, L - T) ────────

@dataclass(frozen=True)
class MemeBudget:
    """Единственный расчёт бюджета: один и тот же для рантайма и витрины.

    ``ceiling`` = L — эффективный потолок итогового image-prompt (минимум
    кандидатов), ``template_chars`` = T — длина шаблона БЕЗ прикола,
    ``joke_budget`` = J = max(0, L - T) — сколько символов остаётся приколу.
    Инвариант: ``T + len(joke) <= L``.

    ``placeholder``: ``slot`` (ровно один ``{joke}``), ``append`` (историческое
    «шаблон + пробел + прикол»), ``invalid`` (два и более плейсхолдера —
    конфигурация отклоняется при сохранении, в рантайме работает append).
    """

    ceiling: int | None
    source: str
    template_chars: int
    joke_budget: int
    known: bool
    placeholder: str = "append"
    candidates: tuple[tuple[str, int], ...] = ()

    def as_dict(self) -> dict:
        return {
            "ceiling": self.ceiling,
            "source": self.source,
            "template_chars": self.template_chars,
            "joke_budget": self.joke_budget,
            "known": self.known,
            "placeholder": self.placeholder,
            "candidates": [
                {"source": name, "value": number}
                for name, number in self.candidates
            ],
        }


def joke_placeholder_count(template: str) -> int:
    """Сколько раз в шаблоне картинки стоит ``{joke}`` (валидно 0 или 1)."""
    return str(template or "").count(JOKE_PLACEHOLDER)


def template_validation_error(template: str) -> str:
    """Причина отказа шаблона картинки ("" — шаблон допустим).

    Контракт §2–§3 ТЗ: плейсхолдер ``{joke}`` допустим в единственном
    экземпляре. Два и более — ошибка конфигурации: сохранение отклоняется
    (422), а не «молча дописывает» второй прикол. Пустой шаблон валиден как
    значение (это не «снять слой»): рантайм отдельно пропускает мем с
    ``template_empty``.
    """
    if joke_placeholder_count(template) > 1:
        return (f"шаблон: допускается не более одного {JOKE_PLACEHOLDER} "
                f"(найдено {joke_placeholder_count(template)})")
    return ""


def template_chars(template: str) -> int:
    """T — длина шаблона без прикола (с разделителем в append-режиме)."""
    head = str(template or "")
    if joke_placeholder_count(head) == 1:
        return len(head.replace(JOKE_PLACEHOLDER, ""))
    # Нет плейсхолдера (или он невалиден) — прикол дописывается через пробел.
    return len(head) + 1


def render_image_prompt(template: str, joke: str) -> str:
    """Итоговый prompt этапа C: шаблон + ПРИКОЛ (не выжимка).

    Валидный шаблон с одним ``{joke}`` подставляет прикол на его место; шаблон
    без плейсхолдера сохраняет исторический вид ``шаблон + ' ' + прикол``.
    """
    body = str(joke or "").strip()
    head = str(template or "")
    if joke_placeholder_count(head) == 1:
        return head.replace(JOKE_PLACEHOLDER, body)
    return f"{head} {body}"


def resolve_meme_budget(*, model_chars: int | None,
                        admin: int | None,
                        explicit: int | None,
                        template: str) -> MemeBudget:
    """L/T/J одной функцией — рантайм и витрина обязаны звать именно её.

    Источник L — тот кандидат, который реально связал итог (минимум). Явный
    override, админская настройка и capability модели не смешиваются в
    безымянный бюджет. Потолок относится к ИТОГОВОМУ prompt (шаблон + прикол),
    а не к выжимке: J — это и есть «сколько остаётся приколу».
    """
    candidates: list[tuple[str, int]] = []
    if explicit is not None and int(explicit) > 0:
        candidates.append(("explicit_override", int(explicit)))
    if admin is not None and int(admin) > 0:
        candidates.append(("admin_setting", int(admin)))
    if model_chars is not None and int(model_chars) > 0:
        candidates.append(("model_capability", int(model_chars)))
    placeholders = joke_placeholder_count(template)
    if placeholders == 1:
        mode = "slot"
    elif placeholders == 0:
        mode = "append"
    else:
        mode = "invalid"
    chars = template_chars(template)
    if not candidates:
        return MemeBudget(ceiling=None, source="unknown", template_chars=chars,
                          joke_budget=0, known=False, placeholder=mode)
    source, value = min(candidates, key=lambda item: (item[1], item[0]))
    return MemeBudget(
        ceiling=int(value), source=source, template_chars=chars,
        joke_budget=max(0, int(value) - int(chars)), known=True,
        placeholder=mode, candidates=tuple(candidates))


def joke_instruction(prompt_text: str, limit: int) -> str:
    """Промпт этапа B + явное ограничение длины (модель знает N ДО генерации)."""
    base = str(prompt_text or "").strip() or MEME_JOKE_PROMPT
    return f"{base}\n\n{JOKE_LENGTH_DIRECTIVE.format(n=int(limit))}"


def trim_joke(joke: str, limit: int) -> tuple[str, bool]:
    """Защитная обрезка перелёта (страховка, НЕ основной механизм).

    Возвращает ``(текст, была ли обрезка)``. По границе слова, если она есть.
    """
    body = str(joke or "").strip()
    if body and int(limit or 0) > 0 and len(body) > int(limit):
        cut = body[:int(limit)]
        space = cut.rfind(" ")
        if space > 0:
            cut = cut[:space]
        return (cut.strip() or body[:int(limit)].strip()), True
    return body, False


# ── промпты: слои настройки по ключу каталога (единый источник — реестр) ────

def active_prompt_view(block_id: str, *, override: str | None = None) -> dict:
    """Эффективный текст через общий реестр. Отдельного хранилища нет."""
    from services import prompt_factory
    return prompt_factory.meme_prompt_view(block_id, pg_value=override)


def prompt_setting_key(block_id: str) -> str:
    """PG-ключ каталога для блока промпта (``""`` — блок объявлен только кодом).

    Ключ берётся у САМОГО блока реестра, а не литералом: один источник правды
    и для чтения слоёв (``effective_meme_prompt``), и для записи (API).
    """
    try:
        from services import prompt_registry as pr
        spec = pr.block(block_id)
        return str(getattr(spec, "pg_key", "") or "")
    except Exception:
        logger.debug("[meme] prompt key unreadable | block=%s", block_id,
                     exc_info=True)
        return ""


async def _prompt_layer(chat_id: int | None, pg_key: str) -> tuple[str, str]:
    """Непустой слой настройки: ``(текст, слой)`` — ``chat`` → ``global``.

    Источник слоя берётся у штатного резолвера `chat_params.get_chat_param_sourced`
    (override скоупа → ConfigCache), поэтому «чат» и «глобальный» различимы:
    без этого карточка не может честно показать, откуда текст, и не может
    снять именно чатовое переопределение.

    Пустое/пробельное значение слоя = слоя нет (``("", "")``): пустота не
    обнуляет промпт, происходит провал на следующий слой.
    """
    if not pg_key:
        return "", ""
    try:
        if chat_id is not None:
            from services import chat_params
            value, source = await chat_params.get_chat_param_sourced(
                int(chat_id), pg_key, None)
            if value is not None and str(value).strip():
                return str(value), ("chat" if source == "chat" else "global")
            return "", ""
        from services import hot_config as hot
        value = hot.get(pg_key, None)
        if value is not None and str(value).strip():
            return str(value), "global"
    except Exception:
        logger.debug("[meme] prompt layer unreadable | key=%s", pg_key,
                     exc_info=True)
    return "", ""


async def effective_meme_prompt(chat_id: int | None, block_id: str, *,
                                explicit: str | None = None,
                                factory: str = "") -> dict:
    """Эффективный мем-промпт: явный override → чат → глобальный → заводской.

    Ключ слоя берётся из САМОГО блока реестра (``pg_key``), а не из литерала:
    правка карточки «Промпты» (глобально) и карточки мемов (чат) действует без
    правки этого сервиса. Пустое/пробельное значение слоя проваливается на
    следующий слой (пустота не обнуляет промпт).

    ``source`` — фактический слой: ``explicit_override`` | ``chat`` |
    ``global`` | ``factory`` (``registry`` — заводская редакция изменена через
    реестр). ``setting_key`` — ключ, которым правят этот промпт.
    """
    text = ""
    layer = ""
    if explicit is not None and str(explicit).strip():
        text, layer = str(explicit), "explicit_override"
    key = prompt_setting_key(block_id)
    if not text:
        text, layer = await _prompt_layer(chat_id, key)
    view: dict = {}
    try:
        view = active_prompt_view(block_id, override=text or None)
    except Exception:
        logger.debug("[meme] prompt view unavailable | block=%s", block_id,
                     exc_info=True)
    if not text:
        text = str(view.get("text") or factory)
        layer = "factory" if not view.get("differs_from_factory") else "registry"
    differs = bool(view.get("differs_from_factory"))
    if not differs and layer in ("explicit_override", "chat", "global"):
        # Реестр не смог назвать заводской текст (нестандартный/тестовый блок):
        # слой настройки всё равно отличие, если текст не равен заводской
        # редакции, переданной вызывающим. Основной источник — реестр; это
        # страховка от ложного «заводской», а не второй расчёт эффективности.
        reference = str(factory or "")
        differs = (str(text) != reference) if reference else True
    return {
        "block_id": block_id,
        "text": text,
        "source": layer or "factory",
        "factory_revision": str(view.get("factory_revision") or ""),
        "revision": view.get("revision") or 0,
        "differs_from_factory": differs,
        "setting_key": key,
    }



# ── день чата ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DayWindow:
    bucket: str
    timezone_name: str
    timezone_source: str
    next_reset_iso: str


def resolve_timezone(chat_id: int | None, *,
                     tz_name: str | None = None,
                     tz_source: str | None = None) -> tuple[str, str]:
    """Имя TZ и источник. Нет настроенной зоны → UTC, source=utc_fallback."""
    if tz_name:
        return str(tz_name), str(tz_source or "explicit")
    try:
        from services.canonical_context import resolve_timezone as _resolve
        from services import hot_config as hot
        from config.settings import settings
        fallback = str(hot.get("limits.summary_timezone",
                               getattr(settings, "SUMMARY_TIMEZONE", "")) or "")
        global_tz = str(hot.get("limits.chat_timezone",
                                getattr(settings, "CHAT_TIMEZONE", "")) or "")
        chosen = global_tz
        source = "global" if global_tz else ""
        if chat_id is not None:
            try:
                from services.chat_params import get_chat_params_cache
                cache = get_chat_params_cache()
                items = getattr(cache, "_items", None) if cache is not None \
                    else None
                entry = items.get(int(chat_id)) if isinstance(items, dict) \
                    else None
                root = entry[1] if entry is not None else None
                override = (root or {}).get("overrides", {}).get(
                    "limits.chat_timezone")
                if override:
                    chosen = str(override)
                    source = "chat"
            except Exception:
                pass
        if not chosen:
            return "UTC", "utc_fallback"
        name = _resolve(chosen, fallback=fallback or "UTC")
        return (name or "UTC"), (source or "utc_fallback")
    except Exception:
        return "UTC", "utc_fallback"


def day_window(chat_id: int | None, now: datetime | None = None, *,
               tz_name: str | None = None,
               tz_source: str | None = None) -> DayWindow:
    name, source = resolve_timezone(chat_id, tz_name=tz_name, tz_source=tz_source)
    try:
        zone = ZoneInfo(name)
    except Exception:
        zone = timezone.utc
        name, source = "UTC", "utc_fallback"
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    local = stamp.astimezone(zone)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    nxt = start + timedelta(days=1)
    return DayWindow(
        bucket=local.date().isoformat(),
        timezone_name=name,
        timezone_source=source,
        next_reset_iso=nxt.isoformat(),
    )


def quiet_hours_block(spec: str, now: datetime, tz_name: str) -> bool:
    """``HH:MM-HH:MM`` в TZ чата. Пусто/неразборчиво → не блокирует."""
    raw = str(spec or "").strip()
    if not raw or "-" not in raw:
        return False
    left, _, right = raw.partition("-")
    try:
        sh, sm = (int(part) for part in left.strip().split(":", 1))
        eh, em = (int(part) for part in right.strip().split(":", 1))
        zone = ZoneInfo(tz_name)
    except Exception:
        return False
    local = now.astimezone(zone)
    minutes = local.hour * 60 + local.minute
    start = sh * 60 + sm
    end = eh * 60 + em
    if start == end:
        return False
    if start < end:
        return start <= minutes < end
    return minutes >= start or minutes < end


# ── квота: свой журнал, бронь до провайдера ─────────────────────────────────

@dataclass(frozen=True)
class ReserveResult:
    ok: bool
    reason: str
    status: str
    already: bool = False
    spent: int = 0
    limit: int = 0


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5, isolation_level=None,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


class SqliteQuotaLedger:
    """Файловый журнал. Каждый reserve — своё соединение и BEGIN IMMEDIATE.

    Так два потока и два процесса не превышают кап и не списывают один
    job_id дважды. ``apply_schema`` вызывает тест и будущий шаг v40;
    горячий путь таблицу сам не создаёт.
    """

    def __init__(self, path: str) -> None:
        self.path = str(path)

    def apply_schema(self) -> None:
        """Применить DDL журнала (тест/миграция v40 + бронь публикации v41).

        Бронь публикации живёт в ТОМ ЖЕ файле (arch §3.2) и нужна мему так же
        обязательно, как журнал: `apply_schema` — единая точка «схема мем-
        пайплайна готова» для тестов и миграций, поэтому применяет оба набора.
        Горячий путь таблицу сам не создаёт.
        """
        conn = _connect(self.path)
        try:
            for statement in SCHEMA_DDL_SQLITE:
                conn.execute(statement)
            try:
                from services import publication_coordination as pubmod
                for statement in pubmod.CLAIM_DDL_SQLITE:
                    conn.execute(statement)
            except Exception:
                logger.warning("[meme] claim schema not applied",
                               exc_info=True)
        finally:
            conn.close()

    def table_present(self) -> bool:
        conn = _connect(self.path)
        try:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (RESERVATION_TABLE,)).fetchone()
            return row is not None
        finally:
            conn.close()

    def reserve(self, *, chat_id: int, day_bucket: str, job_id: str,
                limit: int, tz_name: str, tz_source: str,
                now_ts: int) -> ReserveResult:
        conn = _connect(self.path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            prev = conn.execute(
                f"SELECT status FROM {RESERVATION_TABLE} WHERE job_id=?",
                (job_id,)).fetchone()
            if prev is not None:
                status = str(prev["status"])
                spent = _spent(conn, chat_id, day_bucket)
                conn.execute("COMMIT")
                return ReserveResult(
                    ok=status in COUNTED_STATUSES,
                    reason="already",
                    status=status,
                    already=True,
                    spent=spent,
                    limit=int(limit))
            spent = _spent(conn, chat_id, day_bucket)
            if int(limit) <= 0 or spent >= int(limit):
                conn.execute(
                    f"INSERT INTO {RESERVATION_TABLE} "
                    "(job_id, chat_id, day_bucket, timezone_name, "
                    "timezone_source, status, error_code, created_at) "
                    "VALUES (?, ?, ?, ?, ?, 'denied', ?, ?)",
                    (job_id, int(chat_id), day_bucket, tz_name, tz_source,
                     SKIP_QUOTA, int(now_ts)))
                conn.execute("COMMIT")
                return ReserveResult(ok=False, reason=SKIP_QUOTA,
                                     status="denied", spent=spent,
                                     limit=int(limit))
            conn.execute(
                f"INSERT INTO {RESERVATION_TABLE} "
                "(job_id, chat_id, day_bucket, timezone_name, "
                "timezone_source, status, error_code, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'reserved', '', ?)",
                (job_id, int(chat_id), day_bucket, tz_name, tz_source,
                 int(now_ts)))
            conn.execute("COMMIT")
            return ReserveResult(ok=True, reason="ok", status="reserved",
                                 spent=spent + 1, limit=int(limit))
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.warning("[meme] quota reserve failed", exc_info=True)
            return ReserveResult(ok=False, reason="quota_store_error",
                                 status="", limit=int(limit))
        finally:
            conn.close()

    def mark(self, job_id: str, status: str, error_code: str = "") -> None:
        if status not in ("provider_called", "provider_failed", "released"):
            return
        conn = _connect(self.path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                f"UPDATE {RESERVATION_TABLE} SET status=?, error_code=? "
                "WHERE job_id=? AND status='reserved'",
                (status, error_code, job_id))
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
        finally:
            conn.close()

    def spent(self, chat_id: int, day_bucket: str) -> int:
        conn = _connect(self.path)
        try:
            return _spent(conn, chat_id, day_bucket)
        finally:
            conn.close()

    def fresh_inflight(self, chat_id: int, now_ts: int) -> bool:
        """Чужая незавершённая бронь моложе окна — каскад, не второй слот."""
        conn = _connect(self.path)
        try:
            row = conn.execute(
                f"SELECT created_at FROM {RESERVATION_TABLE} "
                "WHERE chat_id=? AND status='reserved' "
                "ORDER BY created_at DESC LIMIT 1",
                (int(chat_id),)).fetchone()
            if row is None:
                return False
            return int(now_ts) - int(row["created_at"] or 0) < IN_FLIGHT_STALE_SECONDS
        finally:
            conn.close()

    def last_provider_ts(self, chat_id: int) -> int:
        conn = _connect(self.path)
        try:
            row = conn.execute(
                f"SELECT MAX(created_at) AS ts FROM {RESERVATION_TABLE} "
                "WHERE chat_id=? AND status IN ('provider_called', "
                "'provider_failed')",
                (int(chat_id),)).fetchone()
            return int(row["ts"] or 0) if row is not None else 0
        finally:
            conn.close()

    def status_counts(self, chat_id: int, day_bucket: str) -> dict[str, int]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                f"SELECT status, COUNT(*) AS n FROM {RESERVATION_TABLE} "
                "WHERE chat_id=? AND day_bucket=? GROUP BY status",
                (int(chat_id), day_bucket)).fetchall()
            return {str(row["status"]): int(row["n"]) for row in rows}
        finally:
            conn.close()

    def record_attempt(self, row: dict) -> None:
        conn = _connect(self.path)
        try:
            conn.execute(
                f"INSERT OR IGNORE INTO {ATTEMPT_TABLE} "
                "(attempt_id, chat_id, job_id, ts, stage, outcome, "
                "reason_code, detail, limit_source, limit_value, "
                "window_messages) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row["attempt_id"], int(row["chat_id"]), row.get("job_id") or "",
                 int(row["ts"]), row["stage"], row["outcome"],
                 row.get("reason_code") or "", row.get("detail") or "",
                 row.get("limit_source") or "", row.get("limit_value"),
                 row.get("window_messages")))
        finally:
            conn.close()

    def attempts(self, chat_id: int | None, *, limit: int = 20) -> list[dict]:
        conn = _connect(self.path)
        try:
            if chat_id is None:
                rows = conn.execute(
                    f"SELECT * FROM {ATTEMPT_TABLE} ORDER BY ts DESC LIMIT ?",
                    (int(limit),)).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT * FROM {ATTEMPT_TABLE} WHERE chat_id=? "
                    "ORDER BY ts DESC LIMIT ?",
                    (int(chat_id), int(limit))).fetchall()
            return [dict(row) for row in rows]
        except Exception:
            return []
        finally:
            conn.close()


def _spent(conn: sqlite3.Connection, chat_id: int, day_bucket: str) -> int:
    placeholders = ",".join("?" * len(COUNTED_STATUSES))
    row = conn.execute(
        f"SELECT COUNT(*) AS n FROM {RESERVATION_TABLE} "
        f"WHERE chat_id=? AND day_bucket=? AND status IN ({placeholders})",
        (int(chat_id), day_bucket, *COUNTED_STATUSES)).fetchone()
    return int(row["n"] or 0) if row is not None else 0


def quota_view(ledger: SqliteQuotaLedger | None, *, chat_id: int,
               day: DayWindow, limit: int) -> dict:
    if ledger is None or not ledger.table_present():
        return {
            "available": False,
            "reason": SKIP_SCHEMA,
            "limit": int(limit),
            "spent": None,
            "remaining": None,
            "day_bucket": day.bucket,
            "timezone_name": day.timezone_name,
            "timezone_source": day.timezone_source,
            "next_reset": day.next_reset_iso,
        }
    counts = ledger.status_counts(chat_id, day.bucket)
    spent = sum(counts.get(status, 0) for status in COUNTED_STATUSES)
    remaining = max(0, int(limit) - spent) if int(limit) > 0 else 0
    return {
        "available": True,
        "reason": "ok" if int(limit) > 0 and spent < int(limit) else SKIP_QUOTA,
        "limit": int(limit),
        "spent": spent,
        "remaining": remaining,
        "day_bucket": day.bucket,
        "timezone_name": day.timezone_name,
        "timezone_source": day.timezone_source,
        "next_reset": day.next_reset_iso,
        "provider_called": counts.get("provider_called", 0),
        "provider_failed": counts.get("provider_failed", 0),
        "reserved": counts.get("reserved", 0),
        "denied": counts.get("denied", 0),
    }


# ── зависимость от существующей генерации изображений ──────────────────────

async def image_dependency(chat_id: int | None, *,
                           health: Any = None) -> dict:
    """Готовность image-модуля. Второй конфигурации нет: те же ключи."""
    try:
        from services import image_generation as ig
        module_on = await ig.resolve_module_enabled(chat_id)
    except Exception:
        return {"available": False, "reason": SKIP_IMAGE_NOT_CONFIGURED,
                "module_enabled": False, "configured": False,
                "health": "unknown"}
    if not module_on:
        return {"available": False, "reason": SKIP_IMAGE_MODULE_OFF,
                "module_enabled": False, "configured": False,
                "health": "unknown"}
    try:
        from services import hot_config as hot
        from config.settings import settings
        base = str(hot.get(ig.KEY_BASE_URL, settings.IMAGE_BASE_URL) or "").strip()
        model = str(hot.get(ig.KEY_MODEL, settings.IMAGE_MODEL) or "").strip()
        key = str(hot.get(ig.KEY_API_KEY,
                          getattr(settings, "IMAGE_API_KEY", "") or "")
                  or "").strip()
        get_mode = hot.get(ig.KEY_GET_MODE, settings.IMAGE_GET_MODE)
        if isinstance(get_mode, str):
            get_mode = get_mode.strip().lower() in ("1", "true", "yes", "on")
        else:
            get_mode = bool(get_mode)
    except Exception:
        return {"available": False, "reason": SKIP_IMAGE_NOT_CONFIGURED,
                "module_enabled": True, "configured": False,
                "health": "unknown"}
    configured = bool(base and model and (get_mode or key))
    if not configured:
        return {"available": False, "reason": SKIP_IMAGE_NOT_CONFIGURED,
                "module_enabled": True, "configured": False,
                "health": "unknown", "model": model}
    if health is not None:
        ok = health if isinstance(health, bool) else bool(
            getattr(health, "ok", False))
        if not ok:
            return {"available": False, "reason": SKIP_IMAGE_UNHEALTHY,
                    "module_enabled": True, "configured": True,
                    "health": "unhealthy", "model": model}
        return {"available": True, "reason": "ok", "module_enabled": True,
                "configured": True, "health": "healthy", "model": model}
    return {"available": True, "reason": "ok", "module_enabled": True,
            "configured": True, "health": "unknown", "model": model}


async def model_prompt_chars() -> int | None:
    """Capability выбранной image-модели, в символах. Unknown → None."""
    try:
        from services.image_generation import resolve_generate_prompt_limit
        from services.cover_prompt_assembly import limit_to_chars
        limit = resolve_generate_prompt_limit()
        if limit is None or not getattr(limit, "known", False):
            return None
        return limit_to_chars(getattr(limit, "value", None),
                              getattr(limit, "unit", "chars"))
    except Exception:
        return None


# ── случайность ─────────────────────────────────────────────────────────────

@dataclass
class DrawHit:
    ok: bool
    reason: str
    value: float | None = None
    draw_id: str = ""
    #: Единая трассировка решения (§2): те же поля, что у текстовой
    #: инициативы. Фактический источник (`source`/`provider`/`source_impl`/
    #: `fallback_reason`) — из `RandomSourceService`, без выдумывания.
    trace: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return dict(self.trace or {})


async def draw_trigger(source, *, chat_id: int, probability: float) -> DrawHit:
    """Один draw санкционированного purpose ``meme_trigger``.

    Решение принимает ОБЩИЙ контур (`initiative_observer.random_trigger`):
    второй клиент/генератор не создаётся, формат трассировки один на оба
    механизма. Значение из fallback-пути (владелец разрешил
    ``memory.random_fallback_to_pseudorandom``) — ДЕЙСТВИТЕЛЬНОЕ решение:
    отказом считается только ``deferred``/отсутствие значения.
    """
    from services import initiative_observer as obs
    from services import mca_random_source as mrs
    if not mrs.purpose_sanctioned(mrs.PURPOSE_MEME_TRIGGER):
        return DrawHit(False, SKIP_RANDOM_UNAVAILABLE,
                       trace=obs.build_draw_trace(
                           None, purpose=mrs.PURPOSE_MEME_TRIGGER,
                           probability=probability,
                           reason="purpose_not_sanctioned"))
    decision = await obs.random_trigger(
        source, chat_id=chat_id, purpose=mrs.PURPOSE_MEME_TRIGGER,
        probability=probability, shortcut=False)
    # Код причины у мема свой (исторический закрытый набор `SKIP_REASONS`),
    # решение — общее: `random_miss` текстовой инициативы = `no_random_hit`.
    reason = decision.reason
    if not decision.ok:
        reason = (SKIP_RANDOM_MISS if reason == obs.SKIP_RANDOM_MISS
                  else SKIP_RANDOM_UNAVAILABLE)
    return DrawHit(decision.ok, reason,
                   value=decision.value if decision.ok else None,
                   draw_id=str((decision.trace or {}).get("draw_id") or ""),
                   trace=decision.trace)


async def default_random_source(db):
    try:
        from services.mca_random_source import get_service
        return get_service(db)
    except Exception:
        return None


# ── попытка ─────────────────────────────────────────────────────────────────

@dataclass
class AttemptResult:
    chat_id: int
    stage: str
    outcome: str
    reason: str
    detail: str = ""
    job_id: str = ""
    prompt: str = ""
    published: bool = False
    generated: bool = False
    limit: MemeBudget | None = None
    prompt_origin: str = ""
    window_messages: int = 0
    counters: dict = field(default_factory=dict)
    #: Факты этапов (summary/joke/image_generation/publish) — компактный JSON
    #: в существующее поле `detail` строки журнала. Схема БД не меняется.
    stage_facts: dict = field(default_factory=dict)
    #: Текст прикола остаётся ВНУТРИ результата: в чат и в as_dict он не идёт.
    joke: str = ""
    manually_triggered: bool = False

    def as_dict(self) -> dict:
        return {
            "chat_id": self.chat_id,
            "stage": self.stage,
            "outcome": self.outcome,
            "reason": self.reason,
            "detail": self.detail,
            "job_id": self.job_id,
            "published": self.published,
            "generated": self.generated,
            "prompt_origin": self.prompt_origin,
            "window_messages": self.window_messages,
            "limit": self.limit.as_dict() if self.limit else None,
            "stage_facts": dict(self.stage_facts or {}),
            "manual": bool(self.manually_triggered),
            "blocks_text_initiative": False,
            "output_kind": OUTPUT_KIND,
        }


def _remember(row: dict) -> None:
    _PROCESS_ATTEMPTS.append(dict(row))


def compact_facts(facts: dict | None) -> str:
    """Компактный JSON фактов этапа для поля ``detail`` (без текстов прикола)."""
    if not facts:
        return ""
    try:
        return json.dumps(facts, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))
    except (TypeError, ValueError):
        return ""


def parse_attempt_facts(row: dict | str) -> dict:
    """Разбор фактов этапа из ``detail``. Не JSON → пустой словарь.

    Один разборщик на витрину, аналитику и тесты (R2: формат в строке журнала
    слабее типизированной колонки, поэтому читает его ровно одна функция).
    """
    raw = row.get("detail") if isinstance(row, dict) else row
    text = str(raw or "").strip()
    if not text.startswith("{"):
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _finish(result: AttemptResult, *, ledger, now_ts: int,
            settings: MemeSettings) -> AttemptResult:
    stages = [stage for stage in STAGES
              if int((result.counters or {}).get(stage) or 0)]
    if result.stage not in stages:
        stages.append(result.stage)
    for stage in stages:
        terminal = stage == stages[-1]
        facts = compact_facts((result.stage_facts or {}).get(stage))
        # Терминальная строка сохраняет нынешний текстовый detail (код
        # причины важнее фактов); пройденные этапы несут свой JSON фактов.
        detail = (result.detail or facts) if terminal else facts
        row = {
            "attempt_id": uuid.uuid4().hex,
            "chat_id": int(result.chat_id),
            "job_id": result.job_id,
            "ts": int(now_ts),
            "stage": stage,
            "outcome": result.outcome if terminal else "passed",
            "reason_code": result.reason if terminal else "",
            "detail": detail,
            "limit_source": result.limit.source if result.limit else "",
            "limit_value": (result.limit.ceiling if result.limit else None),
            "window_messages": settings.window_messages,
        }
        _remember(row)
        if ledger is not None:
            try:
                ledger.record_attempt(row)
            except Exception:
                logger.warning("[meme] attempt journal failed", exc_info=True)
    result.window_messages = settings.window_messages
    return result



async def _default_messages(db, chat_id: int, limit: int) -> list[dict]:
    raw = getattr(db, "db", db)
    cursor = await raw.execute(WINDOW_SQL, (int(chat_id), int(limit)))
    rows = await cursor.fetchall()
    out = []
    for row in rows or ():
        item = dict(row)
        if int(item.get("chat_id") or chat_id) != int(chat_id):
            continue
        out.append(item)
    return out


async def _default_watermark(db, chat_id: int) -> int | None:
    """Watermark живого окна чата (`MAX(id)`), None — прочитать не удалось.

    Используется ровно одной проверкой: «окно изменилось, пока мем
    генерировался» (INIT-COORD §3.4). Ошибка чтения → None: свежесть не
    выдумывается ни в одну сторону.
    """
    if db is None:
        return None
    try:
        raw = getattr(db, "db", db)
        cursor = await raw.execute(
            "SELECT COALESCE(MAX(id), 0) AS m FROM smart_messages "
            "WHERE chat_id = ? AND import_key IS NULL", (int(chat_id),))
        row = await cursor.fetchone()
        if row is None:
            return None
        value = row["m"] if not isinstance(row, dict) else row.get("m")
        return int(value or 0)
    except Exception:
        return None


async def _default_publish_gate(db, chat_id: int, now_ts: int):
    try:
        from services.direct_chat_service import build_fresh_recheck_context
        from services.mca_intents import SendRecheck
        context = await build_fresh_recheck_context(
            db, int(chat_id),
            {"chat_id": int(chat_id), "created_at": int(now_ts),
             "status": "open"})
        outcome = SendRecheck().check(context)
        if outcome.proceed:
            return True, "ok"
        return False, str(outcome.reason_code or SKIP_PUBLISH)
    except Exception:
        logger.warning("[meme] publish gate unavailable — block", exc_info=True)
        return False, "recheck_unavailable"


async def consider_chat(
        db, chat_id: int, *,
        settings: MemeSettings | None = None,
        ledger: SqliteQuotaLedger | None = None,
        now: datetime | None = None,
        now_ts: int | None = None,
        tz_name: str | None = None,
        tz_source: str | None = None,
        initiative_enabled: Callable[[], bool] | None = None,
        chat_enabled: Callable[[int], Awaitable[bool]] | None = None,
        image_health: Any = None,
        image_status: dict | None = None,
        random_source=None,
        messages: list[dict] | None = None,
        message_reader: Callable[..., Awaitable[list[dict]]] | None = None,
        llm: Any = None,
        summarizer: Callable[..., Awaitable[str]] | None = None,
        joke_generator: Callable[..., Awaitable[str]] | None = None,
        image_provider: Callable[..., Awaitable[Any]] | None = None,
        publish_gate: Callable[..., Awaitable[tuple]] | None = None,
        sender: Callable[..., Awaitable[Any]] | None = None,
        job_id: str | None = None,
        prompt_override: str | None = None,
        model_chars: int | None = None,
        manual: bool = False,
        claim_store=None,
        publication=None,
        watermark_reader: Callable[[int], Awaitable[int | None]] | None = None,
) -> AttemptResult:
    """Одна попытка мема в одном чате. Дорогое — только после дешёвых гейтов.

    Три этапа в одном проходе: A выжимка (без потолка) → B прикол (здесь
    работает J = max(0, L - T)) → C image prompt (шаблон + прикол).

    ``manual=True`` — диагностический запуск (``/meme``): квота, кулдаун,
    минимум сообщений, случайный триггер, тихие часы, in-flight и гейт
    публикации не применяются; права проверяет вызывающий слой, а готовность
    image-модуля, наличие журнала и разрешимость бюджета остаются гейтами.

    ``claim_store``/``publication`` (INIT-COORD §3): бронь публикации. Без
    явной брони она открывается по тому же файлу, что и журнал квоты; таблицы
    нет → честный ``schema_absent`` (мем не отправляется без координации).
    ``watermark_reader`` — шов чтения watermark окна для проверки свежести.
    """
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    ts = int(now_ts if now_ts is not None else stamp.timestamp())
    cfg = settings if settings is not None else await load_settings(chat_id)
    counters = {stage: 0 for stage in STAGES}
    counters[STAGE_CONSIDERED] = 1
    facts: dict[str, dict] = {}

    def skipped(reason: str, *, stage: str = STAGE_SKIPPED,
                detail: str = "", limit: MemeBudget | None = None,
                jid: str = "") -> AttemptResult:
        counters[stage] = counters.get(stage, 0) + 1
        result = AttemptResult(
            chat_id=int(chat_id), stage=stage, outcome="skipped",
            reason=reason, detail=detail, job_id=jid, limit=limit,
            counters=dict(counters), stage_facts=dict(facts),
            manually_triggered=bool(manual))
        return _finish(result, ledger=ledger, now_ts=ts, settings=cfg)

    if initiative_enabled is None:
        def initiative_enabled() -> bool:
            from services.initiative_observer import observer_enabled
            return bool(observer_enabled())
    # Тумблеры — часть авто-инициативы, а не диагностики: ручной запуск
    # обязан работать до включения мемов, иначе отладить нечего.
    if not manual:
        if not initiative_enabled():
            return skipped(SKIP_INITIATIVE_DISABLED)
        if chat_enabled is not None and not await chat_enabled(int(chat_id)):
            return skipped(SKIP_INITIATIVE_DISABLED)
        if not cfg.enabled:
            return skipped(SKIP_DISABLED)

    # Ниже — гейты, которые ручной запуск НЕ обходит: без рабочего image
    # backend мем физически не создать, без журнала некуда писать попытку.
    image = image_status if image_status is not None else \
        await image_dependency(chat_id, health=image_health)
    if not image.get("available"):
        return skipped(str(image.get("reason") or SKIP_IMAGE_NOT_CONFIGURED))

    if ledger is None or not ledger.table_present():
        return skipped(SKIP_SCHEMA)

    day = day_window(chat_id, stamp, tz_name=tz_name, tz_source=tz_source)
    jid = job_id or f"meme:{int(chat_id)}:{day.bucket}:{uuid.uuid4().hex[:12]}"
    if not manual:
        view = quota_view(ledger, chat_id=int(chat_id), day=day,
                          limit=cfg.daily_limit)
        if int(cfg.daily_limit) <= 0 or int(view.get("spent") or 0) >= int(
                cfg.daily_limit):
            return skipped(SKIP_QUOTA)

        last_ts = ledger.last_provider_ts(int(chat_id))
        if cfg.cooldown_seconds and last_ts and \
                ts - last_ts < cfg.cooldown_seconds:
            return skipped(SKIP_COOLDOWN)

        if quiet_hours_block(cfg.quiet_hours, stamp, day.timezone_name):
            return skipped(SKIP_QUIET)

    # ── INIT-COORD §3.1: дешёвая ПРОВЕРКА координации публикаций. Стоит после
    # своих кулдаунов/квоты (свои гейты первичны и честны) и ДО чтения окна и
    # LLM-вызовов: если в чате только что публиковался другой механизм или
    # действует приоритет `/meme`, платить за генерацию незачем.
    coordinator = publication
    if coordinator is None:
        from services import publication_coordination as pubmod
        coordinator = pubmod.PublicationCoordinator(
            db, store=claim_store if claim_store is not None else
            pubmod.open_store(db, path=(ledger.path if ledger is not None
                                        else None)))
    # Таблица брони обязательна для мема (arch §3.6): без неё нет «ровно одной
    # публикации», а тихая отправка «на удачу» запрещена. Текстовая инициатива
    # в этом же состоянии деградирует и публикует — мем останавливается.
    if coordinator.store() is not None and not coordinator.available():
        return skipped(SKIP_SCHEMA, detail="publish_claim_absent", jid=jid)
    precheck = await coordinator.precheck(
        int(chat_id), OUTPUT_KIND, now=ts, manual=bool(manual))
    facts["publication"] = dict(precheck)
    if not precheck.get("ok"):
        reason = str(precheck.get("reason") or SKIP_PUBLICATION_CONFLICT)
        code = (SKIP_PUBLICATION_IN_FLIGHT
                if reason == "publication_in_flight"
                else SKIP_PUBLICATION_CONFLICT)
        return skipped(code, detail=str(precheck.get("detail") or ""), jid=jid)

    if message_reader is not None:
        rows = await message_reader(int(chat_id), cfg.window_messages)
    elif messages is not None:
        rows = [row for row in messages
                if int(row.get("chat_id", chat_id)) == int(chat_id)]
        rows = rows[:cfg.window_messages]
    else:
        rows = await _default_messages(db, int(chat_id), cfg.window_messages)
    foreign = [row for row in rows
               if int(row.get("chat_id", chat_id)) != int(chat_id)]
    if foreign:
        return skipped(SKIP_SUMMARY, detail="chat_mix")
    if not rows:
        # Пустое окно — не «мало сообщений»: генерировать не из чего даже
        # в ручном режиме. Отдельный detail, чтобы причина была видна.
        return skipped(SKIP_ACTIVITY, detail="window_empty", jid=jid)
    if not manual and len(rows) < cfg.min_messages:
        return skipped(SKIP_ACTIVITY, jid=jid)

    if not manual:
        source = random_source
        if source is None:
            source = await default_random_source(db)
        draw = await draw_trigger(source, chat_id=int(chat_id),
                                  probability=cfg.trigger_probability)
        # Трассировка случайного решения (§2) — в факты этапа eligible и, при
        # промахе, тем же JSON в detail строки пропуска: одна правда о draw.
        facts[STAGE_ELIGIBLE] = {"random": dict(draw.trace or {})}
        if not draw.ok:
            return skipped(draw.reason,
                           detail=compact_facts({"random": draw.trace})
                           or draw.draw_id, jid=jid)


    counters[STAGE_ELIGIBLE] = 1

    # ── этап C' — шаблон: T и режим подстановки нужны ДО этапа B ────────────
    image_prompt = await effective_meme_prompt(
        chat_id, IMAGE_PROMPT_BLOCK_ID, explicit=prompt_override,
        factory=MEME_IMAGE_PROMPT)
    template = str(image_prompt.get("text") or "")
    origin = "factory" if image_prompt.get("source") == "factory" else "custom"
    if not template.strip():
        return skipped(SKIP_TEMPLATE_EMPTY, stage=STAGE_FAILED,
                       detail="template_missing", jid=jid)
    if model_chars is None and prompt_override is None:
        model_chars = await model_prompt_chars()
    budget = resolve_meme_budget(
        model_chars=model_chars, admin=cfg.length_admin,
        explicit=cfg.length_override, template=template)
    if not budget.known:
        return skipped(SKIP_LENGTH_UNKNOWN, limit=budget, jid=jid)
    if budget.joke_budget <= 0:
        # J = 0: шаблон уже съел весь потолок. Честный пропуск ДО LLM-вызова.
        return skipped(SKIP_NO_JOKE_BUDGET, limit=budget, jid=jid)

    # Guard «генерация уже идёт» — ДО платной выжимки: иначе чужая свежая
    # бронь съедала бы LLM-вызов впустую (порядок проверок — до дорогих).
    if not manual and ledger.fresh_inflight(int(chat_id), ts) and not job_id:
        return skipped(SKIP_IN_FLIGHT, limit=budget, jid=jid)

    summary_prompt = await effective_meme_prompt(
        chat_id, SUMMARY_PROMPT_BLOCK_ID, factory=MEME_SUMMARY_SYSTEM_PROMPT)
    summary_system = str(summary_prompt.get("text") or MEME_SUMMARY_SYSTEM_PROMPT)
    # ── INIT-COORD §3.4: watermark окна НА СТАРТЕ генерации. После получения
    # брони он перечитывается: если чат успел поговорить, готовая картинка про
    # устаревший контекст НЕ отправляется (`publication_stale`).
    read_watermark = watermark_reader or (
        lambda cid: _default_watermark(db, int(cid)))
    window_watermark = await read_watermark(int(chat_id))

    # ── этап A — выжимка: БЕЗ потолка длины (ни цели, ни обрезки) ───────────
    try:
        if summarizer is None:
            summary = await _default_summarize(
                llm, rows, summary_system, chat_id=int(chat_id),
                model=cfg.summarizer_model)
        else:
            summary = await summarizer(int(chat_id), rows, summary_system)
    except Exception as exc:
        logger.warning("[meme] summary failed | chat=%s | error=%s",
                       chat_id, type(exc).__name__)
        return skipped(SKIP_SUMMARY, stage=STAGE_FAILED,
                       detail=f"exception:{type(exc).__name__}", limit=budget,
                       jid=jid)
    summary = str(summary or "").strip()
    if not summary:
        return skipped(SKIP_SUMMARY, stage=STAGE_FAILED, detail="empty_summary",
                       limit=budget, jid=jid)
    counters[STAGE_SUMMARY] = 1
    facts[STAGE_SUMMARY] = {"chars": len(summary),
                            "source": summary_prompt.get("source")}

    # ── этап B — прикол: единственное место, где работает потолок длины ─────
    joke_prompt = await effective_meme_prompt(
        chat_id, JOKE_PROMPT_BLOCK_ID, factory=MEME_JOKE_PROMPT)
    instruction = joke_instruction(
        str(joke_prompt.get("text") or MEME_JOKE_PROMPT), budget.joke_budget)
    try:
        if joke_generator is None:
            raw_joke = await _default_joke(
                llm, summary, instruction=instruction, chat_id=int(chat_id))
        else:
            raw_joke = await joke_generator(int(chat_id), summary, instruction)
    except Exception as exc:
        logger.warning("[meme] joke failed | chat=%s | error=%s",
                       chat_id, type(exc).__name__)
        return skipped(SKIP_JOKE_FAILED, stage=STAGE_FAILED,
                       detail=f"exception:{type(exc).__name__}", limit=budget,
                       jid=jid)
    joke, trimmed = trim_joke(str(raw_joke or ""), budget.joke_budget)
    if not joke:
        return skipped(SKIP_JOKE_EMPTY, stage=STAGE_FAILED, detail="empty_joke",
                       limit=budget, jid=jid)
    counters[STAGE_JOKE] = 1
    facts[STAGE_JOKE] = {
        "limit": int(budget.joke_budget),
        "template_chars": int(budget.template_chars),
        "ceiling": budget.ceiling,
        "chars": len(joke),
        "trimmed": bool(trimmed),
        "source": str(joke_prompt.get("source") or ""),
        "placeholder": budget.placeholder,
    }

    # ── этап C — итоговый prompt из шаблона и ПРИКОЛА (не выжимки) ──────────
    prompt = render_image_prompt(template, joke)
    facts[STAGE_IMAGE] = {
        "chars": len(prompt),
        "template_chars": int(budget.template_chars),
        "template_revision": str(image_prompt.get("factory_revision") or ""),
        "template_source": str(image_prompt.get("source") or ""),
        "joke_chars": len(joke),
    }

    if manual:
        # Ручной запуск не тратит квоту: брони нет вовсе, строка попытки есть.
        reserved = ReserveResult(ok=True, reason="manual", status="manual")
    else:
        reserved = ledger.reserve(
            chat_id=int(chat_id), day_bucket=day.bucket, job_id=jid,
            limit=cfg.daily_limit, tz_name=day.timezone_name,
            tz_source=day.timezone_source, now_ts=ts)
        if reserved.already:
            if reserved.status == "released":
                # Слот снят (вызов провайдера достоверно не начинался): квота
                # не исчерпана, новый слот берётся другим job_id.
                return skipped(SKIP_SLOT_RELEASED, detail="job_released",
                               limit=budget, jid=jid)
            if reserved.status in ("provider_called", "provider_failed"):
                # Тот же job уже дошёл до провайдера: второй слот не берём и
                # второй платный вызов не делаем.
                return skipped(SKIP_QUOTA, detail="job_already_counted",
                               limit=budget, jid=jid)
            return skipped(SKIP_QUOTA,
                           detail=f"job_{reserved.status or 'denied'}",
                           limit=budget, jid=jid)
        if not reserved.ok:
            return skipped(reserved.reason, limit=budget, jid=jid)

    called = False
    try:
        if image_provider is None:
            provider_result = await _default_image(prompt, int(chat_id), jid)
        else:
            provider_result = await image_provider(prompt, int(chat_id), jid)
        called = bool(getattr(provider_result, "called", True))
        ok = bool(getattr(provider_result, "ok", False))
        reason = str(getattr(provider_result, "reason", "") or "")
        content = getattr(provider_result, "content", None)
    except Exception:
        logger.warning("[meme] image provider failed", exc_info=True)
        called = True
        ok = False
        reason = "exception"
        content = None
    if not called:
        if not manual:
            ledger.mark(jid, "released", reason or "not_called")
        return skipped(SKIP_IMAGE_FAILED, stage=STAGE_FAILED,
                       detail=reason or "not_called", limit=budget, jid=jid)
    if not ok:
        if not manual:
            ledger.mark(jid, "provider_failed", reason or SKIP_IMAGE_FAILED)
        counters[STAGE_IMAGE] = 1
        result = AttemptResult(
            chat_id=int(chat_id), stage=STAGE_FAILED, outcome="failed",
            reason=SKIP_IMAGE_FAILED, detail=reason, job_id=jid,
            generated=False, limit=budget, prompt_origin=origin,
            counters=dict(counters), stage_facts=dict(facts), joke=joke,
            manually_triggered=bool(manual))
        return _finish(result, ledger=ledger, now_ts=ts, settings=cfg)
    if not manual:
        ledger.mark(jid, "provider_called", "")
    counters[STAGE_IMAGE] = 1

    # ── INIT-COORD §3.3/§3.5: атомарная бронь публикации ПЕРЕД гейтом и
    # отправкой. Проигравший не отправляет уже сгенерированную картинку ни
    # сейчас, ни позже; собственный кулдаун/квота при этом не сбрасываются.
    claim = await coordinator.acquire(
        int(chat_id), OUTPUT_KIND, holder_ref=jid, now=ts,
        manual=bool(manual))
    # Диагностика координации — в отдельный (не этапный) слот фактов: строка
    # этапа publish остаётся ровно своим контрактом (gate/manual).
    pub_facts = facts.setdefault("publication", {})
    if not isinstance(pub_facts, dict):
        pub_facts = {}
        facts["publication"] = pub_facts
    pub_facts["manual"] = bool(manual)
    pub_facts["claim"] = claim.as_dict()
    if not claim.granted:
        counters[STAGE_PUBLISH] = 1
        counters[STAGE_SKIPPED] = counters.get(STAGE_SKIPPED, 0) + 1
        code = (SKIP_PUBLICATION_IN_FLIGHT
                if claim.reason == "publication_in_flight"
                else SKIP_PUBLICATION_CONFLICT)
        result = AttemptResult(
            chat_id=int(chat_id), stage=STAGE_PUBLISH, outcome="skipped",
            reason=code, detail=str(claim.detail or claim.reason or ""),
            job_id=jid, prompt=prompt, published=False, generated=True,
            limit=budget, prompt_origin=origin, counters=dict(counters),
            stage_facts=dict(facts), joke=joke,
            manually_triggered=bool(manual))
        return _finish(result, ledger=ledger, now_ts=ts, settings=cfg)

    async def _drop_claim(reason_code: str, *, detail: str = "",
                          stage: str = STAGE_PUBLISH) -> AttemptResult:
        """Отмена после брони: аренда освобождается, watermark публикации НЕ
        пишется (публикации не было), причина честная."""
        await coordinator.release(int(chat_id), claim.claim_id, published=False,
                                  holder_kind=OUTPUT_KIND, holder_ref=jid,
                                  now=ts)
        counters[STAGE_PUBLISH] = 1
        counters[STAGE_SKIPPED] = counters.get(STAGE_SKIPPED, 0) + 1
        result = AttemptResult(
            chat_id=int(chat_id), stage=stage, outcome="skipped",
            reason=reason_code, detail=detail, job_id=jid, prompt=prompt,
            published=False, generated=True, limit=budget,
            prompt_origin=origin, counters=dict(counters),
            stage_facts=dict(facts), joke=joke,
            manually_triggered=bool(manual))
        return _finish(result, ledger=ledger, now_ts=ts, settings=cfg)

    # ── свежесть: окно чата изменилось, пока генерировали? ─────────────────
    if window_watermark is not None:
        current_watermark = await read_watermark(int(chat_id))
        pub_facts["watermark"] = {
            "at_generation": int(window_watermark),
            "at_publish": (int(current_watermark)
                           if current_watermark is not None else None),
        }
        if current_watermark is not None and \
                int(current_watermark) != int(window_watermark):
            return await _drop_claim(SKIP_PUBLICATION_STALE,
                                     detail="window_changed")

    if manual:
        # Диагностика не соревнуется с авто-инициативой и не ждёт гейта.
        allowed, gate_reason = True, "manual_bypass"
    elif publish_gate is None:
        allowed, gate_reason = await _default_publish_gate(db, int(chat_id), ts)
    else:
        allowed, gate_reason = await publish_gate(int(chat_id))
    facts.setdefault(STAGE_PUBLISH, {})["gate"] = str(gate_reason or "")
    facts[STAGE_PUBLISH]["manual"] = bool(manual)
    if not allowed or sender is None:
        # Честная причина: гейт мог быть открыт, а отправителя нет вообще.
        detail = (str(gate_reason or SKIP_PUBLISH) if not allowed
                  else "publisher_not_bound")
        blocked = await _drop_claim(SKIP_PUBLISH, detail=detail)
        blocked.outcome = "blocked"
        return blocked
    # ── `claimed → sending` — единственное разрешение звать sender ─────────
    sending = await coordinator.begin_sending(int(chat_id), claim.claim_id,
                                              now=ts, manual=bool(manual))
    pub_facts["sending"] = sending.as_dict()
    if not sending.granted:
        code = (SKIP_PUBLICATION_IN_FLIGHT
                if sending.reason == "publication_in_flight"
                else SKIP_PUBLICATION_EXPIRED)
        return await _drop_claim(code, detail=str(sending.detail or ""))
    try:
        # Доставка не меняется: sender получает ТОЛЬКО изображение; prompt и
        # прикол остаются внутренними (никогда не caption и не сообщение).
        message = await sender(int(chat_id), content, prompt)
    except Exception:
        logger.warning("[meme] publish failed", exc_info=True)
        counters[STAGE_FAILED] = 1
        await coordinator.release(int(chat_id), claim.claim_id,
                                  published=False, holder_kind=OUTPUT_KIND,
                                  holder_ref=jid, now=ts)
        result = AttemptResult(
            chat_id=int(chat_id), stage=STAGE_PUBLISH, outcome="blocked",
            reason=SKIP_PUBLISH, detail="send_failed", job_id=jid,
            prompt=prompt, published=False, generated=True, limit=budget,
            prompt_origin=origin, counters=dict(counters),
            stage_facts=dict(facts), joke=joke,
            manually_triggered=bool(manual))
        return _finish(result, ledger=ledger, now_ts=ts, settings=cfg)
    counters[STAGE_PUBLISH] = 1
    tg_message_id = getattr(message, "message_id", None)
    ledger_output_id = await _record_meme_output(
        db, chat_id=int(chat_id), tg_message_id=tg_message_id, sent_at=ts,
        correlation_id=jid, manual=bool(manual))
    pub_facts["output"] = {"ledger_id": ledger_output_id,
                           "tg_message_id": tg_message_id}
    await coordinator.release(int(chat_id), claim.claim_id, published=True,
                              holder_kind=OUTPUT_KIND, holder_ref=jid, now=ts)
    result = AttemptResult(
        chat_id=int(chat_id), stage=STAGE_PUBLISH, outcome="published",
        reason="sent", job_id=jid, prompt=prompt, published=True,
        generated=True, limit=budget, prompt_origin=origin,
        counters=dict(counters), stage_facts=dict(facts), joke=joke,
        manually_triggered=bool(manual))
    return _finish(result, ledger=ledger, now_ts=ts, settings=cfg)


async def _record_meme_output(db, *, chat_id: int, tg_message_id, sent_at: int,
                              correlation_id: str, manual: bool) -> int | None:
    """Записать доставленный мем в СУЩЕСТВУЮЩИЙ журнал выводов (INIT-COORD §1 V3).

    Свой kind `meme_initiative` делает вывод мема видимым общим антифлуд/
    cooldown-хелперам: без этой записи `_last_bot_output_age` не видел картинку,
    и текстовая инициатива могла ответить сразу после мема. Запись — только по
    факту доставки (недоставленное не является словами бота). Ошибка записи не
    рвёт успешную публикацию: она видна в логе.
    """
    if db is None:
        return None
    try:
        from services import bot_output_ledger as ledger_mod
        return await ledger_mod.record_delivered_output(
            db, chat_id=int(chat_id), tg_message_id=tg_message_id, text=None,
            caption=None, output_kind=OUTPUT_KIND, sent_at=int(sent_at),
            correlation_id=str(correlation_id or ""),
            source_feature="evol014_meme_initiative")
    except Exception:
        logger.warning("[meme] output ledger record failed | chat=%s",
                       chat_id, exc_info=True)
        return None


#: Предел ожидания лёгкого LLM-вызова выжимки в этом же проходе инициативы.
SUMMARY_TIMEOUT_SECONDS = 45
#: Предел ожидания обязательного этапа B. Короче выжимки: прикол — короткий
#: текст, а проход инициативы не должен висеть из-за него.
JOKE_TIMEOUT_SECONDS = 30


async def _default_summarize(llm, rows, system_prompt: str, *,
                             chat_id: int | None = None,
                             model: str = "") -> str:
    """Этап A: лёгкий контур выжимки — ОДИН вызов существующего LLM-клиента.

    Тяжёлый summary-pipeline (planner → writer → reviewer) не используется.
    Потолка длины здесь НЕТ (MEME-PIPELINE-REFactor-01 §1): в payload не
    уходит ``target_chars``, постфактум-обрезки тоже нет. Нет клиента/вызова —
    честный ``RuntimeError``, не тихая подстановка чужого текста.
    """
    generate = getattr(llm, "generate", None) if llm is not None else None
    if generate is None:
        raise RuntimeError("summarizer_unavailable")
    effective_model = str(getattr(llm, "_chat_model", "") or "")
    if model and effective_model and model != effective_model:
        # Осознанно: отдельного клиента под выжимку не создаём, поэтому
        # настроенная модель не подменяется тихо — она видна в настройках,
        # а фактический вызов идёт моделью общего клиента (как у соседних
        # лёгких вызовов инициативы).
        logger.info("[meme] summarizer_model=%s не применяется общим "
                    "клиентом; фактическая модель=%s", model, effective_model)
    payload = {
        "messages": [
            {"id": row.get("id"), "text": str(row.get("text") or "")[:500]}
            for row in rows
        ],
    }
    messages = [
        {"role": "system", "content": str(system_prompt or "")},
        {"role": "user",
         "content": json.dumps(payload, ensure_ascii=False,
                               separators=(",", ":"))},
    ]
    raw = await asyncio.wait_for(
        generate(messages, temperature=0.2,
                 chat_id=int(chat_id) if chat_id is not None else None,
                 module="initiative", step="meme_summary",
                 correlation_id=uuid.uuid4().hex[:16]),
        timeout=SUMMARY_TIMEOUT_SECONDS)
    return str(raw or "").strip()


async def _default_joke(llm, summary: str, *, instruction: str,
                        chat_id: int | None = None) -> str:
    """Этап B: ОДИН LLM-вызов — выжимка превращается в короткий абсурдный прикол.

    Модель получает выжимку и инструкцию, в которой уже стоит явное
    ограничение длины N = J (§3 ТЗ): ограничение действует ДО генерации,
    а не обрезкой постфактум. Нет клиента — честный ``RuntimeError``
    (``joke_generation_failed``), а не подстановка выжимки вместо прикола.
    """
    generate = getattr(llm, "generate", None) if llm is not None else None
    if generate is None:
        raise RuntimeError("joke_client_unavailable")
    messages = [
        {"role": "system", "content": str(instruction or "")},
        {"role": "user", "content": str(summary or "").strip()},
    ]
    raw = await asyncio.wait_for(
        generate(messages, temperature=0.8,
                 chat_id=int(chat_id) if chat_id is not None else None,
                 module="initiative", step="meme_joke",
                 correlation_id=uuid.uuid4().hex[:16]),
        timeout=JOKE_TIMEOUT_SECONDS)
    return str(raw or "").strip()



async def _default_image(prompt: str, chat_id: int, job_id: str):
    from services.image_generation import generate
    result = await generate(prompt, chat_id=chat_id, correlation_id=job_id,
                            consume_budget=False)
    return type("ProviderResult", (), {
        "called": True,
        "ok": bool(getattr(result, "ok", False)),
        "reason": str(getattr(result, "reason", "") or ""),
        "content": getattr(result, "content", None),
    })()


async def on_initiative_cycle(db, chat_ids, *, state: dict | None = None,
                              **kwargs) -> list[AttemptResult]:
    """Точка вызова из прохода Initiative. Пустой список чатов — no-op.

    Падение одной попытки не валит ни остальные чаты, ни текстовую
    инициативу, но и не выдаётся за провал выжимки: пишется отдельная
    причина ``cycle_exception`` и строка журнала попыток.

    ``state`` — durable per-chat состояние механизма (payload прохода): туда
    пишется диагностика §7 (последняя/следующая проверка, причина, конфликт
    публикаций, собственный кулдаун). Новых таблиц диагностики нет.
    """
    results = []
    for chat_id in chat_ids or ():
        try:
            result = await consider_chat(db, int(chat_id), **kwargs)
            results.append(result)
            await _note_state(state, result, kwargs)
        except Exception as exc:
            logger.warning("[meme] chat attempt raised — initiative continues "
                           "| chat=%s | error=%s", chat_id,
                           type(exc).__name__, exc_info=True)
            failure = _bridge_failure(int(chat_id), exc, **kwargs)
            results.append(failure)
            await _note_state(state, failure, kwargs)
    return results


async def _note_state(state: dict | None, result: AttemptResult,
                      kwargs: dict) -> None:
    """Диагностика попытки в payload прохода (по каждому механизму отдельно).

    Поля: последняя проверка, следующая проверка, случайное решение и его
    фактический источник, выполненные условия, причина пропуска, собственный
    кулдаун, конфликт публикаций. Источник чисел — уже существующие журнал
    попыток/настройки, ничего не пересчитывается заново.
    """
    if not isinstance(state, dict):
        return
    cfg = kwargs.get("settings")
    if not isinstance(cfg, MemeSettings):
        cfg = None
    now_ts = kwargs.get("now_ts")
    if now_ts is None:
        stamp = kwargs.get("now")
        now_ts = int(stamp.timestamp()) if isinstance(stamp, datetime) \
            else int(datetime.now(timezone.utc).timestamp())
    facts = dict(result.stage_facts or {})
    random_trace = dict((facts.get(STAGE_ELIGIBLE) or {}).get("random") or {})
    publication = dict(facts.get("publication") or {})
    ledger = kwargs.get("ledger")
    last_provider_ts = 0
    try:
        if ledger is not None:
            last_provider_ts = int(ledger.last_provider_ts(int(result.chat_id)))
    except Exception:
        last_provider_ts = 0
    cooldown = int(cfg.cooldown_seconds) if cfg is not None else 0
    next_check = max(int(now_ts), last_provider_ts + max(0, cooldown))
    if str(result.reason or "") == SKIP_QUOTA:
        # Квота суток: следующая реальная возможность — начало нового дня.
        try:
            window = day_window(int(result.chat_id), None)
            next_check = max(next_check, int(datetime.fromisoformat(
                window.next_reset_iso).timestamp()))
        except Exception:
            pass
    state[str(int(result.chat_id))] = {
        "output_kind": OUTPUT_KIND,
        "last_check_ts": int(now_ts),
        "next_check_ts": int(next_check),
        "random": random_trace,
        "reason": str(result.reason or ""),
        "reason_label": _reason_label(result.reason),
        "stage": str(result.stage or ""),
        "conditions": {
            "considered": int((result.counters or {}).get(STAGE_CONSIDERED)
                              or 0),
            "eligible": int((result.counters or {}).get(STAGE_ELIGIBLE) or 0),
            "summary": int((result.counters or {}).get(STAGE_SUMMARY) or 0),
            "joke": int((result.counters or {}).get(STAGE_JOKE) or 0),
            "image": int((result.counters or {}).get(STAGE_IMAGE) or 0),
            "publish": int((result.counters or {}).get(STAGE_PUBLISH) or 0),
        },
        "cooldown_seconds": cooldown,
        "publication": publication,
        "job_id": str(result.job_id or ""),
        "published": bool(result.published),
    }


def _reason_label(reason_code) -> str:
    """Ярлык причины через общий словарь инициативы (не выдумываем текст)."""
    try:
        from services.initiative_observer import reason_label
        return reason_label(reason_code)
    except Exception:
        return str(reason_code or "")


def _bridge_failure(chat_id: int, exc: BaseException,
                    **kwargs) -> AttemptResult:
    """Ошибка моста: отдельная причина, честная запись, не ``summary_failed``."""
    counters = {stage: 0 for stage in STAGES}
    counters[STAGE_CONSIDERED] = 1
    counters[STAGE_FAILED] = 1
    result = AttemptResult(
        chat_id=int(chat_id), stage=STAGE_FAILED, outcome="failed",
        reason=SKIP_CYCLE_EXCEPTION,
        detail=f"{type(exc).__name__}", counters=counters)
    settings = kwargs.get("settings")
    if not isinstance(settings, MemeSettings):
        settings = MemeSettings()
    now_ts = kwargs.get("now_ts")
    if now_ts is None:
        stamp = kwargs.get("now")
        now_ts = int(stamp.timestamp()) if isinstance(stamp, datetime) \
            else int(datetime.now(timezone.utc).timestamp())
    try:
        _finish(result, ledger=kwargs.get("ledger"), now_ts=int(now_ts),
                settings=settings)
    except Exception:
        logger.warning("[meme] bridge failure journaling failed",
                       exc_info=True)
    return result


def _joke_stats(rows: list[dict]) -> dict:
    """Сводка по этапу B из разобранных фактов (без текстов приколов)."""
    attempts = 0
    chars_total = 0
    trimmed = 0
    for row in rows:
        if str(row.get("stage") or "") != STAGE_JOKE:
            continue
        facts = parse_attempt_facts(row)
        if "chars" not in facts:
            continue
        try:
            chars_total += int(facts.get("chars") or 0)
        except (TypeError, ValueError):
            continue
        attempts += 1
        if facts.get("trimmed"):
            trimmed += 1
    return {
        "attempts": attempts,
        "avg_chars": (round(chars_total / attempts, 1) if attempts else None),
        "trimmed": trimmed,
    }


def analytics_snapshot(ledger: SqliteQuotaLedger | None, *,
                       chat_id: int | None = None,
                       day: DayWindow | None = None,
                       limit: int = DEFAULT_DAILY_LIMIT) -> dict:
    """Счётчики мемов. Не складываются с текстовой инициативой."""
    rows: list[dict]
    coverage = "process_local"
    if ledger is not None and ledger.table_present():
        rows = ledger.attempts(chat_id)
        coverage = "durable"
    else:
        rows = [row for row in reversed(_PROCESS_ATTEMPTS)
                if chat_id is None or int(row.get("chat_id") or 0) == int(chat_id)]
        coverage = "schema_absent" if ledger is None else "process_local"
    counters = {stage: 0 for stage in STAGES}
    reasons: dict[str, int] = {}
    for row in rows:
        stage = str(row.get("stage") or "")
        if stage in counters:
            counters[stage] += 1
        reason = str(row.get("reason_code") or "")
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
    quota = None
    if day is not None and chat_id is not None:
        quota = quota_view(ledger, chat_id=int(chat_id), day=day, limit=limit)
    return {
        "output_kind": OUTPUT_KIND,
        "separate_from_initiative": True,
        "coverage": coverage,
        "counters": counters,
        "skip_reasons": reasons,
        "joke": _joke_stats(rows),
        "attempts": rows[:20],
        "quota": quota,
        "enabled_default": DEFAULT_ENABLED,
    }



async def availability(chat_id: int | None, *,
                       settings: MemeSettings | None = None,
                       ledger: SqliteQuotaLedger | None = None,
                       image_health: Any = None,
                       initiative_on: bool | None = None,
                       publication: Any = None,
                       now: int | None = None) -> dict:
    """Готовность мем-механизма + его собственная диагностика (§7).

    Диагностика отдельная от текстовой инициативы: последняя/следующая
    проверка, результат случайного решения с фактическим источником,
    выполненные условия, причина пропуска, СВОЙ кулдаун и признак конфликта
    публикаций. Источники — только существующие журнал попыток/ledger/бронь;
    новых таблиц нет.
    """
    cfg = settings if settings is not None else await load_settings(chat_id)
    if initiative_on is None:
        try:
            from services.initiative_observer import observer_enabled
            initiative_on = bool(observer_enabled())
        except Exception:
            initiative_on = False
    image = await image_dependency(chat_id, health=image_health)
    schema_ok = ledger is not None and ledger.table_present()
    reason = "ok"
    if not initiative_on:
        reason = SKIP_INITIATIVE_DISABLED
    elif not cfg.enabled:
        reason = SKIP_DISABLED
    elif not image.get("available"):
        reason = str(image.get("reason") or SKIP_IMAGE_NOT_CONFIGURED)
    elif not schema_ok:
        reason = SKIP_SCHEMA
    stamp = int(now if now is not None else datetime.now(timezone.utc)
                .timestamp())
    diagnostics = _availability_diagnostics(
        cfg, ledger=ledger, chat_id=chat_id, reason=reason, now=stamp,
        publication=publication)
    return {
        "available": reason == "ok",
        "reason": reason,
        "meme_enabled": cfg.enabled,
        "initiative_enabled": bool(initiative_on),
        "image": image,
        "schema_present": schema_ok,
        "settings": cfg.as_dict(),
        "blocks_text_initiative": False,
        # INIT-COORD §7: восемь полей диагностики механизма — отдельно от
        # текстовой инициативы, в существующем ответе сервиса.
        "diagnostics": diagnostics,
    }


def _availability_diagnostics(cfg: MemeSettings, *, ledger, chat_id,
                              reason: str, now: int,
                              publication: Any = None) -> dict:
    """Диагностика мем-механизма из существующих источников (без новых таблиц)."""
    last_check = 0
    last_reason = ""
    last_facts: dict = {}
    try:
        if ledger is not None and chat_id is not None:
            last_check = int(ledger.last_provider_ts(int(chat_id)) or 0)
        rows = ledger.attempts(chat_id, limit=1) if ledger is not None else []
        if rows:
            row = rows[0]
            last_reason = str(row.get("reason_code") or "")
            last_facts = parse_attempt_facts(row)
    except Exception:
        last_check, last_reason, last_facts = 0, "", {}
    cooldown = int(cfg.cooldown_seconds or 0)
    remaining = 0
    if cooldown and last_check:
        remaining = max(0, cooldown - max(0, now - last_check))
    next_check = max(now, last_check + cooldown) if cooldown else now
    random_trace = dict(last_facts.get("random") or {})
    publish_view: dict = {}
    if publication is not None:
        try:
            publish_view = dict(publication)
        except Exception:
            publish_view = {}
    elif chat_id is not None:
        try:
            from services import publication_coordination as pubmod
            store = pubmod.open_store(None, path=getattr(ledger, "path", None))
            if store is not None and store.table_present():
                row = store.snapshot(int(chat_id)) or {}
                interval = pubmod.default_interval_seconds()
                last_pub = row.get("last_publish_ts")
                age = (max(0, now - int(last_pub)) if last_pub else None)
                publish_view = {
                    "available": True,
                    "state": str(row.get("state") or ""),
                    "holder_kind": str(row.get("holder_kind") or ""),
                    "last_publish_kind": str(row.get("last_publish_kind")
                                             or ""),
                    "other_age_seconds": age,
                    "interval_seconds": interval,
                    "manual_priority_until": row.get("manual_priority_until"),
                    "conflict": bool(
                        age is not None and interval > 0
                        and str(row.get("last_publish_kind") or "")
                        != OUTPUT_KIND and age < interval),
                }
        except Exception:
            publish_view = {"available": False}
    return {
        "last_check_ts": last_check,
        "next_check_ts": int(next_check),
        "random": random_trace,
        "conditions": {
            "initiative_enabled": reason != SKIP_INITIATIVE_DISABLED,
            "meme_enabled": bool(cfg.enabled),
            "image_ready": reason not in (SKIP_IMAGE_MODULE_OFF,
                                          SKIP_IMAGE_NOT_CONFIGURED,
                                          SKIP_IMAGE_UNHEALTHY),
            "schema_present": reason != SKIP_SCHEMA,
            "cooldown_ready": remaining <= 0,
        },
        "skip_reason": (last_reason if reason == "ok" else reason),
        "cooldown_seconds": cooldown,
        "cooldown_remaining_seconds": int(remaining),
        "publication": publish_view,
    }
