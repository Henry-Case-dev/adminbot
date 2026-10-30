"""EVOL-014 — инициативные мемы: capability внутри цикла Initiative.

Это не замена инициативы и не отдельный cron. Решение «пробовать ли мем»
принимает существующий проход ``initiative.observe``; здесь живёт только
способность собрать выжимку одного чата и заказать картинку.

Инварианты:
  * свой тумблер, заводской OFF; выключение мемов не трогает текстовую
    инициативу; выключение Initiative останавливает и мемы;
  * триггер — только санкционированный контур ``mca_random_source``
    (purpose ``meme_trigger``). Недоступность контура → ``random_unavailable``.
    Локального ``random`` / Math.random нет;
  * окно сообщений и cooldown конфигурируются (дефолт окна 500 — не кап);
  * потолок длины считается ДО выжимки и передаётся суммаризатору как цель;
    постфактум-обрезки нет;
  * заводской image-prompt — дословный префикс ``Создай мем с шрифтом импакт:``
    плюс выжимка; текст берётся из реестра промптов;
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
#: Дословно, слово в слово. После двоеточия подставляется выжимка.
MEME_IMAGE_PROMPT = "Создай мем с шрифтом импакт:"

#: Лёгкая инструкция выжимки. Числовой потолок в константу не зашит:
#: его передают вызовом, уже посчитанным из capability/настройки.
MEME_SUMMARY_SYSTEM_PROMPT = (
    "Собери короткую выжимку именно под мем из сообщений одного чата. "
    "Нужен мемный хук: конфликт, шутка, повтор, абсурд или локальный инсайд, "
    "а не пересказ разговора вообще. Не добавляй фактов, которых нет в окне. "
    "Потолок символов передаётся отдельно и является целевым размером "
    "выжимки: уложись в него сразу. Верни только текст выжимки, без кавычек, "
    "заголовков и пояснений."
)

IMAGE_PROMPT_BLOCK_ID = "initiative.meme.image"
SUMMARY_PROMPT_BLOCK_ID = "initiative.meme.summary"
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

SKIP_REASONS = (
    SKIP_DISABLED, SKIP_INITIATIVE_DISABLED, SKIP_IMAGE_MODULE_OFF,
    SKIP_IMAGE_NOT_CONFIGURED, SKIP_IMAGE_UNHEALTHY, SKIP_RANDOM_UNAVAILABLE,
    SKIP_RANDOM_MISS, SKIP_COOLDOWN, SKIP_SUMMARY, SKIP_IMAGE_FAILED,
    SKIP_PUBLISH, SKIP_QUOTA, SKIP_ACTIVITY, SKIP_SCHEMA, SKIP_LENGTH_UNKNOWN,
    SKIP_IN_FLIGHT, SKIP_QUIET, SKIP_CYCLE_EXCEPTION, SKIP_SLOT_RELEASED,
)

STAGE_CONSIDERED = "considered"
STAGE_ELIGIBLE = "eligible"
STAGE_SUMMARY = "summary"
STAGE_IMAGE = "image_generation"
STAGE_PUBLISH = "publish"
STAGE_FAILED = "failed"
STAGE_SKIPPED = "skipped"
STAGES = (
    STAGE_CONSIDERED, STAGE_ELIGIBLE, STAGE_SUMMARY, STAGE_IMAGE,
    STAGE_PUBLISH, STAGE_FAILED, STAGE_SKIPPED,
)

COUNTED_STATUSES = ("reserved", "provider_called", "provider_failed")
SCHEMA_VERSION_TARGET = 40
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

#: Тот же контракт для PostgreSQL (v40). Типы аддитивные, без сброса данных.
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


def schema_integration_note() -> str:
    """Заметка для следующего шага схемы. database.py/pg_db.py здесь не правятся."""
    return (
        f"v{SCHEMA_VERSION_TARGET}: аддитивные таблицы {RESERVATION_TABLE} и "
        f"{ATTEMPT_TABLE}. v39 занят журналом промптов. Пока миграция не "
        "применена, отсутствие таблицы — честный schema_absent, без вызова "
        "image-провайдера и без авто-CREATE на горячем пути. DDL: "
        "SCHEMA_DDL_SQLITE / SCHEMA_DDL_POSTGRES."
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


# ── длина: считается ДО выжимки, без последующей обрезки ───────────────────

@dataclass(frozen=True)
class LengthLimit:
    value: int | None
    source: str
    summary_target: int | None
    prefix_chars: int
    known: bool
    candidates: tuple[tuple[str, int], ...] = ()

    def as_dict(self) -> dict:
        return {
            "value": self.value,
            "source": self.source,
            "summary_target": self.summary_target,
            "prefix_chars": self.prefix_chars,
            "known": self.known,
            "candidates": [
                {"source": name, "value": number}
                for name, number in self.candidates
            ],
        }


def resolve_length_limit(*, model_chars: int | None,
                         admin: int | None,
                         explicit: int | None,
                         prefix: str) -> LengthLimit:
    """Эффективный потолок всего image-prompt и цель выжимки.

    Источник — тот кандидат, который реально связал итог (минимум).
    Явный override, админская настройка и capability модели не смешиваются
    в безымянный бюджет. Цель выжимки = потолок минус префикс и пробел,
    чтобы суммаризатор сразу писал под N, а не под «потом обрежем».
    """
    candidates: list[tuple[str, int]] = []
    if explicit is not None and int(explicit) > 0:
        candidates.append(("explicit_override", int(explicit)))
    if admin is not None and int(admin) > 0:
        candidates.append(("admin_setting", int(admin)))
    if model_chars is not None and int(model_chars) > 0:
        candidates.append(("model_capability", int(model_chars)))
    prefix_chars = len(prefix or "")
    if not candidates:
        return LengthLimit(value=None, source="unknown", summary_target=None,
                           prefix_chars=prefix_chars, known=False)
    source, value = min(candidates, key=lambda item: (item[1], item[0]))
    # Пробел между префиксом и выжимкой входит в потолок prompt'а.
    separator = 1 if prefix_chars else 0
    target = value - prefix_chars - separator
    if target <= 0:
        return LengthLimit(value=value, source=source, summary_target=None,
                           prefix_chars=prefix_chars, known=False,
                           candidates=tuple(candidates))
    return LengthLimit(value=value, source=source, summary_target=target,
                       prefix_chars=prefix_chars, known=True,
                       candidates=tuple(candidates))


def build_image_prompt(prefix: str, summary: str, *,
                       summary_target: int | None) -> tuple[str, str]:
    """``prefix + ' ' + summary``. Длиннее цели — отказ, не срез.

    Возвращает ``(prompt, error)``. ``error`` пуст только если выжимка
    уже уложилась в заранее посчитанную цель.
    """
    text = str(summary or "").strip()
    head = str(prefix or "")
    if not text:
        return "", "empty_summary"
    if summary_target is not None and len(text) > int(summary_target):
        return "", "exceeded_precomputed_limit"
    return f"{head} {text}", ""


def active_prompt_view(block_id: str, *, override: str | None = None) -> dict:
    """Эффективный текст через общий реестр. Отдельного хранилища нет."""
    from services import prompt_factory
    return prompt_factory.meme_prompt_view(block_id, pg_value=override)


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
        conn = _connect(self.path)
        try:
            for statement in SCHEMA_DDL_SQLITE:
                conn.execute(statement)
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


async def draw_trigger(source, *, chat_id: int, probability: float) -> DrawHit:
    """Один draw санкционированного purpose. Свой fallback не подставляется."""
    from services import mca_random_source as mrs
    if not mrs.purpose_sanctioned(mrs.PURPOSE_MEME_TRIGGER):
        return DrawHit(False, SKIP_RANDOM_UNAVAILABLE)
    if source is None:
        return DrawHit(False, SKIP_RANDOM_UNAVAILABLE)
    try:
        result = await source.draw_probability(
            chat_id=chat_id, purpose=mrs.PURPOSE_MEME_TRIGGER,
            probability=probability)
    except Exception:
        logger.warning("[meme] random draw failed", exc_info=True)
        return DrawHit(False, SKIP_RANDOM_UNAVAILABLE)
    if result is None or getattr(result, "deferred", False):
        return DrawHit(False, SKIP_RANDOM_UNAVAILABLE)
    if getattr(result, "fallback_reason", None):
        # Контур подменил quantum на PRNG сам. Для мема это недоступность,
        # а не тихое согласие владельца.
        return DrawHit(False, SKIP_RANDOM_UNAVAILABLE)
    if getattr(result, "value", None) is None:
        return DrawHit(False, SKIP_RANDOM_UNAVAILABLE)
    try:
        value = float(result.value)
    except (TypeError, ValueError):
        return DrawHit(False, SKIP_RANDOM_UNAVAILABLE)
    if value >= float(probability):
        return DrawHit(False, SKIP_RANDOM_MISS, value=value,
                       draw_id=str(getattr(result, "draw_id", "") or ""))
    return DrawHit(True, "ok", value=value,
                   draw_id=str(getattr(result, "draw_id", "") or ""))


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
    limit: LengthLimit | None = None
    prompt_origin: str = ""
    window_messages: int = 0
    counters: dict = field(default_factory=dict)

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
            "blocks_text_initiative": False,
            "output_kind": OUTPUT_KIND,
        }


def _remember(row: dict) -> None:
    _PROCESS_ATTEMPTS.append(dict(row))


def _finish(result: AttemptResult, *, ledger, now_ts: int,
            settings: MemeSettings) -> AttemptResult:
    stages = [stage for stage in STAGES
              if int((result.counters or {}).get(stage) or 0)]
    if result.stage not in stages:
        stages.append(result.stage)
    for stage in stages:
        terminal = stage == stages[-1]
        row = {
            "attempt_id": uuid.uuid4().hex,
            "chat_id": int(result.chat_id),
            "job_id": result.job_id,
            "ts": int(now_ts),
            "stage": stage,
            "outcome": result.outcome if terminal else "passed",
            "reason_code": result.reason if terminal else "",
            "detail": result.detail if terminal else "",
            "limit_source": result.limit.source if result.limit else "",
            "limit_value": result.limit.value if result.limit else None,
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
        image_provider: Callable[..., Awaitable[Any]] | None = None,
        publish_gate: Callable[..., Awaitable[tuple]] | None = None,
        sender: Callable[..., Awaitable[Any]] | None = None,
        job_id: str | None = None,
        prompt_override: str | None = None,
        model_chars: int | None = None,
) -> AttemptResult:
    """Одна попытка мема в одном чате. Дорогое — только после дешёвых гейтов."""
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    ts = int(now_ts if now_ts is not None else stamp.timestamp())
    cfg = settings if settings is not None else await load_settings(chat_id)
    counters = {stage: 0 for stage in STAGES}
    counters[STAGE_CONSIDERED] = 1

    def skipped(reason: str, *, stage: str = STAGE_SKIPPED,
                detail: str = "", limit: LengthLimit | None = None,
                jid: str = "") -> AttemptResult:
        counters[stage] = counters.get(stage, 0) + 1
        result = AttemptResult(
            chat_id=int(chat_id), stage=stage, outcome="skipped",
            reason=reason, detail=detail, job_id=jid, limit=limit,
            counters=dict(counters))
        return _finish(result, ledger=ledger, now_ts=ts, settings=cfg)

    if initiative_enabled is None:
        def initiative_enabled() -> bool:
            from services.initiative_observer import observer_enabled
            return bool(observer_enabled())
    if not initiative_enabled():
        return skipped(SKIP_INITIATIVE_DISABLED)
    if chat_enabled is not None and not await chat_enabled(int(chat_id)):
        return skipped(SKIP_INITIATIVE_DISABLED)
    if not cfg.enabled:
        return skipped(SKIP_DISABLED)

    image = image_status if image_status is not None else \
        await image_dependency(chat_id, health=image_health)
    if not image.get("available"):
        return skipped(str(image.get("reason") or SKIP_IMAGE_NOT_CONFIGURED))

    if ledger is None or not ledger.table_present():
        return skipped(SKIP_SCHEMA)

    day = day_window(chat_id, stamp, tz_name=tz_name, tz_source=tz_source)
    view = quota_view(ledger, chat_id=int(chat_id), day=day,
                      limit=cfg.daily_limit)
    if int(cfg.daily_limit) <= 0 or int(view.get("spent") or 0) >= int(
            cfg.daily_limit):
        return skipped(SKIP_QUOTA)

    last_ts = ledger.last_provider_ts(int(chat_id))
    if cfg.cooldown_seconds and last_ts and ts - last_ts < cfg.cooldown_seconds:
        return skipped(SKIP_COOLDOWN)

    if quiet_hours_block(cfg.quiet_hours, stamp, day.timezone_name):
        return skipped(SKIP_QUIET)

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
    if len(rows) < cfg.min_messages:
        return skipped(SKIP_ACTIVITY)

    source = random_source
    if source is None:
        source = await default_random_source(db)
    draw = await draw_trigger(source, chat_id=int(chat_id),
                              probability=cfg.trigger_probability)
    if not draw.ok:
        return skipped(draw.reason, detail=draw.draw_id)

    counters[STAGE_ELIGIBLE] = 1
    prompt_view = active_prompt_view(IMAGE_PROMPT_BLOCK_ID,
                                     override=prompt_override)
    prefix = str(prompt_view.get("text") or MEME_IMAGE_PROMPT)
    origin = "custom" if prompt_view.get("differs_from_factory") else "factory"
    if model_chars is None and prompt_override is None:
        model_chars = await model_prompt_chars()
    limit = resolve_length_limit(
        model_chars=model_chars, admin=cfg.length_admin,
        explicit=cfg.length_override, prefix=prefix)
    if not limit.known or limit.summary_target is None:
        result = skipped(SKIP_LENGTH_UNKNOWN, limit=limit)
        result.prompt_origin = origin
        return result

    summary_prompt = active_prompt_view(SUMMARY_PROMPT_BLOCK_ID)
    jid = job_id or f"meme:{int(chat_id)}:{day.bucket}:{uuid.uuid4().hex[:12]}"
    # Guard «генерация уже идёт» — ДО платной выжимки: иначе чужая свежая
    # бронь съедала бы LLM-вызов впустую (порядок проверок — до дорогих).
    if ledger.fresh_inflight(int(chat_id), ts) and not job_id:
        return skipped(SKIP_IN_FLIGHT, limit=limit, jid=jid)
    try:
        if summarizer is None:
            summary = await _default_summarize(
                llm, rows, int(limit.summary_target),
                str(summary_prompt.get("text") or MEME_SUMMARY_SYSTEM_PROMPT),
                chat_id=int(chat_id), model=cfg.summarizer_model)
        else:
            summary = await summarizer(
                int(chat_id), rows, int(limit.summary_target),
                str(summary_prompt.get("text") or MEME_SUMMARY_SYSTEM_PROMPT))
    except Exception as exc:
        logger.warning("[meme] summary failed | chat=%s | error=%s",
                       chat_id, type(exc).__name__)
        counters[STAGE_FAILED] = 1
        return skipped(SKIP_SUMMARY, stage=STAGE_FAILED,
                       detail=f"exception:{type(exc).__name__}", limit=limit,
                       jid=jid)
    counters[STAGE_SUMMARY] = 1
    prompt, error = build_image_prompt(
        prefix, str(summary or ""), summary_target=limit.summary_target)
    if error:
        counters[STAGE_FAILED] = 1
        return skipped(SKIP_SUMMARY, stage=STAGE_FAILED, detail=error,
                       limit=limit, jid=jid)

    reserved = ledger.reserve(
        chat_id=int(chat_id), day_bucket=day.bucket, job_id=jid,
        limit=cfg.daily_limit, tz_name=day.timezone_name,
        tz_source=day.timezone_source, now_ts=ts)
    if reserved.already:
        if reserved.status == "released":
            # Слот снят (вызов провайдера достоверно не начинался): квота
            # не исчерпана, новый слот берётся другим job_id.
            return skipped(SKIP_SLOT_RELEASED, detail="job_released",
                           limit=limit, jid=jid)
        if reserved.status in ("provider_called", "provider_failed"):
            # Тот же job уже дошёл до провайдера: второй слот не берём и
            # второй платный вызов не делаем.
            return skipped(SKIP_QUOTA, detail="job_already_counted",
                           limit=limit, jid=jid)
        return skipped(SKIP_QUOTA, detail=f"job_{reserved.status or 'denied'}",
                       limit=limit, jid=jid)
    if not reserved.ok:
        return skipped(reserved.reason, limit=limit, jid=jid)

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
        ledger.mark(jid, "released", reason or "not_called")
        counters[STAGE_FAILED] = 1
        return skipped(SKIP_IMAGE_FAILED, stage=STAGE_FAILED,
                       detail=reason or "not_called", limit=limit, jid=jid)
    if not ok:
        ledger.mark(jid, "provider_failed", reason or SKIP_IMAGE_FAILED)
        counters[STAGE_IMAGE] = 1
        counters[STAGE_FAILED] = 1
        result = AttemptResult(
            chat_id=int(chat_id), stage=STAGE_FAILED, outcome="failed",
            reason=SKIP_IMAGE_FAILED, detail=reason, job_id=jid,
            generated=False, limit=limit, prompt_origin=origin,
            counters=dict(counters))
        return _finish(result, ledger=ledger, now_ts=ts, settings=cfg)
    ledger.mark(jid, "provider_called", "")
    counters[STAGE_IMAGE] = 1

    if publish_gate is None:
        allowed, gate_reason = await _default_publish_gate(db, int(chat_id), ts)
    else:
        allowed, gate_reason = await publish_gate(int(chat_id))
    if not allowed or sender is None:
        counters[STAGE_PUBLISH] = 1
        counters[STAGE_SKIPPED] = counters.get(STAGE_SKIPPED, 0) + 1
        # Честная причина: гейт мог быть открыт, а отправителя нет вообще.
        detail = (str(gate_reason or SKIP_PUBLISH) if not allowed
                  else "publisher_not_bound")
        result = AttemptResult(
            chat_id=int(chat_id), stage=STAGE_PUBLISH, outcome="blocked",
            reason=SKIP_PUBLISH,
            detail=detail,
            job_id=jid, prompt=prompt, published=False, generated=True,
            limit=limit, prompt_origin=origin, counters=dict(counters))
        return _finish(result, ledger=ledger, now_ts=ts, settings=cfg)
    try:
        await sender(int(chat_id), content, prompt)
    except Exception:
        logger.warning("[meme] publish failed", exc_info=True)
        counters[STAGE_FAILED] = 1
        result = AttemptResult(
            chat_id=int(chat_id), stage=STAGE_PUBLISH, outcome="blocked",
            reason=SKIP_PUBLISH, detail="send_failed", job_id=jid,
            prompt=prompt, published=False, generated=True, limit=limit,
            prompt_origin=origin, counters=dict(counters))
        return _finish(result, ledger=ledger, now_ts=ts, settings=cfg)
    counters[STAGE_PUBLISH] = 1
    result = AttemptResult(
        chat_id=int(chat_id), stage=STAGE_PUBLISH, outcome="published",
        reason="sent", job_id=jid, prompt=prompt, published=True,
        generated=True, limit=limit, prompt_origin=origin,
        counters=dict(counters))
    return _finish(result, ledger=ledger, now_ts=ts, settings=cfg)


#: Предел ожидания лёгкого LLM-вызова выжимки в этом же проходе инициативы.
SUMMARY_TIMEOUT_SECONDS = 45


async def _default_summarize(llm, rows, target: int, system_prompt: str, *,
                             chat_id: int | None = None,
                             model: str = "") -> str:
    """Лёгкий контур выжимки: ОДИН вызов существующего LLM-клиента.

    Тяжёлый summary-pipeline (planner → writer → reviewer) не используется.
    ``target`` — уже посчитанная до вызова цель в символах: она уходит
    суммаризатору как задание («уложись в N»), а не проверяется обрезкой
    постфактум. Нет клиента/вызова — честный ``RuntimeError``, не тихая
    подстановка чужого текста.
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
        "target_chars": int(target),
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


async def on_initiative_cycle(db, chat_ids, **kwargs) -> list[AttemptResult]:
    """Точка вызова из прохода Initiative. Пустой список чатов — no-op.

    Падение одной попытки не валит ни остальные чаты, ни текстовую
    инициативу, но и не выдаётся за провал выжимки: пишется отдельная
    причина ``cycle_exception`` и строка журнала попыток.
    """
    results = []
    for chat_id in chat_ids or ():
        try:
            results.append(await consider_chat(db, int(chat_id), **kwargs))
        except Exception as exc:
            logger.warning("[meme] chat attempt raised — initiative continues "
                           "| chat=%s | error=%s", chat_id,
                           type(exc).__name__, exc_info=True)
            results.append(
                _bridge_failure(int(chat_id), exc, **kwargs))
    return results


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
        "attempts": rows[:20],
        "quota": quota,
        "enabled_default": DEFAULT_ENABLED,
    }


async def availability(chat_id: int | None, *,
                       settings: MemeSettings | None = None,
                       ledger: SqliteQuotaLedger | None = None,
                       image_health: Any = None,
                       initiative_on: bool | None = None) -> dict:
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
    return {
        "available": reason == "ok",
        "reason": reason,
        "meme_enabled": cfg.enabled,
        "initiative_enabled": bool(initiative_on),
        "image": image,
        "schema_present": schema_ok,
        "settings": cfg.as_dict(),
        "blocks_text_initiative": False,
    }
