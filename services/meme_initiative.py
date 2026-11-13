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
    ограничивается здесь, но ТОЛЬКО при фиксированном потолке:
    ``J = max(0, L - T)`` уходит модели явной инструкцией, защитная обрезка —
    только страховка от перелёта;
  * P0.5 (HOTFIX 03.11.2026, §1.4): пустой/``None``/``0`` потолок = АВТО.
    Числового предела нет → директива длины не подставляется, прикол не
    обрезается, выжимка не трогается. Фиктивные «800/0 символов» не
    подставляются: если провайдер отклонит длину, это честный
    ``image_generation_failed`` с его собственной причиной;
  * этап B — АВТОРСКАЯ речь: system собирает единый речевой композер
    (``compose_speech_system``), поэтому прикол придумывает персонаж в своём
    характере (Core/Identity/Expression/базовая речь/юмор/приём Humor Craft/
    Style Policy), а редактируемый промпт остаётся заданием. Второго
    композера, дубля Core, нового агента и доп. LLM-вызовов нет;
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
  * публикация НЕ проверяет «свежесть переписки» (§1.2 P0): новые сообщения,
    реакции, ``latest_message_id``/watermark и обычный рост чата готовый мем
    НЕ отменяют. На старте генерации фиксируется СНАПШОТ ИСТОЧНИКА (чат, run,
    исходные сообщения и их версии, цель/режим) — это входной материал мема,
    а не требование «чат замер». Перед отправкой перепроверяются только
    содержательные условия: тумблеры, наличие исходных сообщений, техническая
    пригодность output, существующая бронь/ledger и publish-гейт;
  * стадии и публикация различаются событиями (``source_snapshot`` →
    ``digest_ready`` → ``joke_ready`` → ``image_ready`` →
    ``publication_requested`` → ``publication_deferred_conflict`` |
    ``publication_sent`` | ``publication_cancelled``/``publication_failed`` |
    ``delivery_unknown``): «генерация прошла» ≠ «отправка прошла»;
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# EVOL-REPLY-CONTEXT-INTEGRITY-01 v5 (§4.1 P7/§4.2 п.2): речевая проекция
# прогона для выжимки мема. Импорт ленивый-совместимый (модуль тянет
# canonical_context только здесь), цикла нет: canonical_context не импортирует
# meme_initiative.
from services.canonical_context import (  # noqa: E402  (после logger)
    SpeechProjection,
    emit_speech_projection_event,
    resolve_item_id,
    speech_projection_enabled,
)

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

#: MEME-JOKE-SPEECH: этап B собирает system ЕДИНЫМ речевым композером
#: (`services.prompt_composer.compose_speech_system`). Задание (редактируемый
#: промпт + J-директива) — только слой `channel_contract`; личность, характер,
#: «Речь и характер», базовая речь/юмор, приём Humor Craft, примеры и Style
#: Policy приходят теми же резолверами, что у Direct/-инициативы.
JOKE_SPEECH_WRITER = "meme_joke"
#: Кода плана ответа у жанра нет честно: закрытая причина композера (§SKIP_REASONS).
JOKE_PLAN_SKIP = "no_l1_plan_in_genre"

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
#: P0.5 §1.4: исторический код «потолок неизвестен». Новым кодом НЕ
#: эмитится: пустой потолок = АВТО (генерация без числового предела), а не
#: пропуск. Оставлен ради ярлыка/чтения исторических строк журнала.
SKIP_LENGTH_UNKNOWN = "length_limit_unknown"
SKIP_IN_FLIGHT = "in_flight"
SKIP_QUIET = "quiet_hours"
#: Мост «цикл инициативы → мем» сломался. Это НЕ провал выжимки: выжимка
#: могла вообще не вызываться. Отдельный код, чтобы аналитика не врала.
SKIP_CYCLE_EXCEPTION = "cycle_exception"
#: Retry уже снятой брони (вызов провайдера достоверно не начинался).
SKIP_SLOT_RELEASED = "slot_released"
#: P0 §1.2.4: исходный материал мема реально исчез (все сообщения снапшота
#: удалены из чата). Доказанная утрата валидности — не «чат изменился».
SKIP_SOURCE_GONE = "source_material_gone"
#: B2 (§1.2.4/§3.3): право публикации в этом чате отозвано — чат больше не
#: допустимая цель (нет в реальном ростере кандидатов), либо у автора ручного
#: запроса больше нет прав. Свой код, не общий `publish_blocked`.
SKIP_RIGHTS_REVOKED = "rights_revoked"
#: B1 (§1.2.5): отложенный артефакт не доставлен за срок жизни (ретенция =
#: собственный кулдаун механизма). Честный терминальный код, не тихая потеря.
SKIP_DEFERRED_EXPIRED = "deferred_publication_expired"
#: Факт «исход отправки неизвестен» (существующий ярлык/протокол координации).
#: Не политика пропуска: так помечается только реально неизвестная доставка.
REASON_DELIVERY_UNKNOWN = "delivery_unknown"
#: P0IM-D7 / S5-MEME: попытка ОБОРВАНА извне (рестарт сервиса, отмена задачи).
#: ``asyncio.CancelledError`` — ``BaseException``, его не видит ни один
#: ``except Exception`` пайплайна: без явной обработки запуск исчезал молча
#: (ни строки журнала, ни ответа пользователю). Это НЕ пропуск по логике
#: мемов и не «устаревание»: свой код, а реальный этап остановки — рядом,
#: в поле ``stage`` той же терминальной строки.
REASON_RUN_INTERRUPTED = "run_interrupted"
#: INIT-COORD (03.11.2026): координация публикаций двух механизмов.
SKIP_PUBLICATION_CONFLICT = "publication_conflict"
SKIP_PUBLICATION_IN_FLIGHT = "publication_in_flight"
#: ИСТОРИЧЕСКИЙ код (P0, 03.11.2026): раньше означал «окно чата изменилось
#: за время генерации». Такой проверки больше НЕТ (§1.2.2): готовый мем не
#: отменяется из-за нового сообщения/watermark. Код остаётся в таксономии
#: только для чтения старых строк журнала.
SKIP_PUBLICATION_STALE = "publication_stale"
SKIP_PUBLICATION_EXPIRED = "publication_expired"

SKIP_REASONS = (
    SKIP_DISABLED, SKIP_INITIATIVE_DISABLED, SKIP_IMAGE_MODULE_OFF,
    SKIP_IMAGE_NOT_CONFIGURED, SKIP_IMAGE_UNHEALTHY, SKIP_RANDOM_UNAVAILABLE,
    SKIP_RANDOM_MISS, SKIP_COOLDOWN, SKIP_SUMMARY, SKIP_JOKE_FAILED,
    SKIP_JOKE_EMPTY, SKIP_NO_JOKE_BUDGET, SKIP_TEMPLATE_EMPTY,
    SKIP_IMAGE_FAILED, SKIP_PUBLISH, SKIP_QUOTA, SKIP_ACTIVITY, SKIP_SCHEMA,
    SKIP_LENGTH_UNKNOWN, SKIP_IN_FLIGHT, SKIP_QUIET, SKIP_CYCLE_EXCEPTION,
    SKIP_SLOT_RELEASED, SKIP_SOURCE_GONE, SKIP_PUBLICATION_CONFLICT,
    SKIP_PUBLICATION_IN_FLIGHT, SKIP_PUBLICATION_STALE,
    SKIP_PUBLICATION_EXPIRED, SKIP_RIGHTS_REVOKED, SKIP_DEFERRED_EXPIRED,
)

# ── события попытки (§1.3 P0): стадии генерации ≠ доставка ──────────────────
#: Снапшот входа конкретного мема (что именно сгенерировано и из чего).
EVENT_SOURCE_SNAPSHOT = "source_snapshot"
#: Выжимка готова (этап A).
EVENT_DIGEST_READY = "digest_ready"
#: Прикол готов (этап B).
EVENT_JOKE_READY = "joke_ready"
#: Картинка готова (этап C) — доставки ещё не было.
EVENT_IMAGE_READY = "image_ready"
#: Бронь взята: запрос на публикацию заявлен.
EVENT_PUBLICATION_REQUESTED = "publication_requested"
#: Публикацию отложил реальный конфликт координации (не «устаревание»).
EVENT_PUBLICATION_DEFERRED = "publication_deferred_conflict"
#: Изображение реально доставлено (единственный факт отправки).
EVENT_PUBLICATION_SENT = "publication_sent"
#: Отмена по содержательному терминальному условию (тумблер/источник/гейт).
EVENT_PUBLICATION_CANCELLED = "publication_cancelled"
#: Публикация технически невозможна (нет отправителя) — доставки не было.
EVENT_PUBLICATION_FAILED = "publication_failed"
#: Факт доставки НЕ подтверждён (и не опровергнут): существующий протокол.
EVENT_DELIVERY_UNKNOWN = "delivery_unknown"

MEME_EVENTS = (
    EVENT_SOURCE_SNAPSHOT, EVENT_DIGEST_READY, EVENT_JOKE_READY,
    EVENT_IMAGE_READY, EVENT_PUBLICATION_REQUESTED,
    EVENT_PUBLICATION_DEFERRED, EVENT_PUBLICATION_SENT,
    EVENT_PUBLICATION_CANCELLED, EVENT_PUBLICATION_FAILED,
    EVENT_DELIVERY_UNKNOWN,
)

#: Режим попытки в событиях/снапшоте (ручной ``/meme`` vs авто-инициатива).
MODE_MANUAL = "manual"
MODE_AUTOMATIC = "automatic"
#: Цель/причина попытки — часть снапшота источника (§1.2.1).
PURPOSE_MANUAL = "meme_manual"
PURPOSE_AUTOMATIC = "meme_initiative"
#: Верхняя граница длины списка событий одной попытки (bounded JSON в журнале).
MAX_EVENTS_PER_ATTEMPT = 24

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


def _attempt_journal_writer(db):
    """Асинхронный писатель строки попытки на соединении `DatabaseService`.

    Журнал живёт в ТОМ ЖЕ файле, что и данные бота, поэтому отдельное
    `sqlite3`-соединение конкурирует с единственным писателем приложения: пока
    чужая транзакция открыта, `INSERT` ждёт `busy_timeout` и падает
    (production 13.11.2026: три полных ожидания по 5 с и spool). Единый
    писатель (`DatabaseService.serialized`) сериализует запись с остальными,
    поэтому ожидание становится асинхронным и заканчивается успехом, а не
    spool. Новых таблиц/очередей нет — тот же журнал, тот же `INSERT`.

    Нет `DatabaseService` (тесты, файл без сервиса) → `None`: остаётся
    прежний файловый путь `record_attempt`.
    """
    try:
        serialized = getattr(db, "serialized", None)
        conn = getattr(db, "db", None)
    except Exception:                     # «сломанный» источник (диагностика)
        return None
    if not callable(serialized) or conn is None:
        return None

    async def _write(sql: str, params: tuple) -> None:
        # Транзакцией уже владеет эта же задача (`serialized` реентрантен):
        # коммит делает владелец, иначе чужая работа зафиксировалась бы раньше.
        if getattr(db, "_write_owner", None) is asyncio.current_task():
            await conn.execute(sql, params)
            return
        async with serialized():
            await conn.execute(sql, params)
            await conn.commit()

    return _write


def open_ledger(db) -> SqliteQuotaLedger | None:
    """Журнал, если таблица уже есть. Не создаёт схему."""
    path = sqlite_path_of(db)
    if not path:
        return None
    ledger = SqliteQuotaLedger(path, writer=_attempt_journal_writer(db))
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

    Два РАЗНЫХ состояния (§1.4 P0.5), и они не смешиваются:

    * ``known=True`` (режим ``fixed``) — есть числовой потолок L:
      ``ceiling`` = L (минимум кандидатов), ``template_chars`` = T — длина
      РЕАЛЬНО зарендеренного image prompt без прикола (production renderer,
      вместе с разделителем), ``joke_budget`` = J = max(0, L - T) — сколько
      символов остаётся приколу. Инвариант: ``T + len(joke) <= L``.
    * ``known=False`` (режим ``auto``) — числового предела НЕТ: пустой
      потолок не превращается ни в 0, ни в 800. ``joke_budget`` в отчётах —
      ``None`` («определяет провайдер»), в рантайме директива длины не
      подставляется и прикол не обрезается.

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

    @property
    def mode(self) -> str:
        """``fixed`` — фиксированный потолок, ``auto`` — его нет."""
        return "fixed" if self.known else "auto"

    def as_dict(self) -> dict:
        return {
            "ceiling": self.ceiling,
            "source": self.source,
            # Режим называется явно: витрина не угадывает «пусто» по 0/null.
            "mode": self.mode,
            "template_chars": self.template_chars,
            # Числа НЕТ — значит его и не показываем (никаких «0 символов»).
            "joke_budget": int(self.joke_budget) if self.known else None,
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


def template_chars(template: str) -> int:
    """T — длина РЕАЛЬНО зарендеренного prompt БЕЗ прикола (§1.4.3).

    Считается production-renderer'ом (``render_image_prompt`` с пустым
    приколом), а не длиной видимого textarea: постоянные части, разделитель
    append-режима и скрытая обвязка входят в число так же, как попадают в
    payload провайдеру. Второго расчёта «на глаз» нет.
    """
    return len(render_image_prompt(template, ""))


def image_prompt_fits(prompt: str, budget: MemeBudget) -> bool:
    """Факт: реально зарендеренный prompt укладывается в фиксированный L.

    В режиме ``auto`` предела нет — проверять нечего (``True``). Проверка
    стоит ПЕРЕД вызовом провайдера: испорченную (переполненную) шутку не
    генерируем и не обрезаем «по живому».
    """
    if not budget.known or budget.ceiling is None:
        return True
    return len(str(prompt or "")) <= int(budget.ceiling)


def resolve_meme_budget(*, model_chars: int | None,
                        admin: int | None,
                        explicit: int | None,
                        template: str) -> MemeBudget:
    """L/T/J одной функцией — рантайм и витрина обязаны звать именно её.

    Источник L — тот кандидат, который реально связал итог (минимум). Явный
    override, админская настройка и capability модели не смешиваются в
    безымянный бюджет. Потолок относится к ИТОГОВОМУ prompt (шаблон + прикол),
    а не к выжимке: J — это и есть «сколько остаётся приколу».

    Нет ни одного положительного кандидата = РЕЖИМ АВТО (§1.4.1): ни 0, ни
    NaN, ни подставное «800». Такой бюджет не блокирует пайплайн — он
    означает «числового предела не задано».
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
        return MemeBudget(ceiling=None, source="auto", template_chars=chars,
                          joke_budget=0, known=False, placeholder=mode)
    source, value = min(candidates, key=lambda item: (item[1], item[0]))
    return MemeBudget(
        ceiling=int(value), source=source, template_chars=chars,
        joke_budget=max(0, int(value) - int(chars)), known=True,
        placeholder=mode, candidates=tuple(candidates))


def joke_instruction(prompt_text: str, limit: int | None) -> str:
    """Промпт этапа B (+ явное ограничение длины при фиксированном L).

    ``limit is None`` = режим АВТО: директива не дописывается, фиктивного
    «не более 0/800 символов» нет. Естественное требование «короткий прикол»
    остаётся в самом редактируемом промпте.
    """
    base = str(prompt_text or "").strip() or MEME_JOKE_PROMPT
    if limit is None or int(limit) <= 0:
        return base
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
                     tz_source: str | None = None,
                     strict: bool = False) -> tuple[str, str]:
    """Имя TZ и источник. Нет настроенной зоны → UTC, source=utc_fallback.

    ``strict=True`` (P0IM-S6-TZ, только витрина диагностики): сбой ЧТЕНИЯ
    слоя настроек не выдаётся за «зона не задана» — исключение уходит
    вызывающему, и тот честно показывает «неизвестно» вместо подставленного
    UTC. Отсутствие настройки (ни чатовой, ни глобальной) — это факт, а не
    сбой: и в строгом режиме возвращается ``utc_fallback``. Боевой путь
    (`day_window`) остаётся fail-open и вызывает без ``strict``.
    """
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
            # MOD-ACL-UX-01 M2 (E-инвентарь): override читается единой
            # синхронной точкой `chat_params.read_override_sync`, а не
            # приватным `ChatParamsCache._items` этого модуля.
            try:
                from services import chat_params as _cp
                override, found = _cp.read_override_sync(
                    int(chat_id), "limits.chat_timezone")
                if found and override:
                    chosen = str(override)
                    source = "chat"
            except Exception:
                # Строгий режим: нечитаемый чатовый слой НЕ означает «override
                # отсутствует» — иначе витрина выдала бы глобальное значение за
                # собственное значение чата.
                if strict:
                    raise
        if not chosen:
            return "UTC", "utc_fallback"
        name = _resolve(chosen, fallback=fallback or "UTC")
        return (name or "UTC"), (source or "utc_fallback")
    except Exception:
        if strict:
            raise
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


def quiet_hours_end(spec: str, now: datetime, tz_name: str) -> int | None:
    """Момент ОКОНЧАНИЯ тихих часов, если они сейчас действуют, иначе ``None``.

    Разбирается ТОТ ЖЕ ``HH:MM-HH:MM``, что и ``quiet_hours_block`` (один
    формат, один разбор); значение нужно витрине, чтобы показать конец паузы
    без выдуманного ETA. Пусто/неразборчиво/не блокирует → ``None``.
    """
    raw = str(spec or "").strip()
    if not raw or "-" not in raw:
        return None
    left, _, right = raw.partition("-")
    try:
        sh, sm = (int(part) for part in left.strip().split(":", 1))
        eh, em = (int(part) for part in right.strip().split(":", 1))
        zone = ZoneInfo(tz_name)
    except Exception:
        return None
    if sh * 60 + sm == eh * 60 + em:
        return None
    if not quiet_hours_block(spec, now, tz_name):
        return None
    local = now.astimezone(zone)
    minutes = local.hour * 60 + local.minute
    start, end = sh * 60 + sm, eh * 60 + em
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    # Окно через полночь: пока мы «до конца» (утро) — конец сегодня, иначе завтра.
    extra_days = 1 if (start > end and minutes >= start) else 0
    finish = day_start + timedelta(days=extra_days, hours=eh, minutes=em)
    try:
        return int(finish.timestamp())
    except Exception:                        # pragma: no cover - defensive
        return None


# ── квота: свой журнал, бронь до провайдера ─────────────────────────────────

@dataclass(frozen=True)
class ReserveResult:
    ok: bool
    reason: str
    status: str
    already: bool = False
    spent: int = 0
    limit: int = 0


#: Сколько раз пробуем записать строку журнала попытки до durable-фолбэка.
ATTEMPT_WRITE_ATTEMPTS = 3
#: Паузы между попытками (сек): покрывают транзиентную блокировку файла.
ATTEMPT_WRITE_DELAYS = (0.02, 0.08)
#: busy_timeout записей журнала квоты и чтений (паритет с приложением, 5 с).
JOURNAL_BUSY_TIMEOUT_MS = 5000
#: busy_timeout ЗАПИСИ строки попытки. Синхронный `sqlite3` исполняется в
#: петле событий, поэтому ожидание чужого писателя длиной в полный
#: `busy_timeout` = заморозка бота на всё это время. Production 13.11.2026
#: (09:36): три попытки × 5.0 с = 15.1 с заморозки и всё равно spool.
#: Теперь ожидание короткое и завершается durable-спулом, а не зависанием.
ATTEMPT_JOURNAL_BUSY_TIMEOUT_MS = 250
#: Операция журнала попыток — для диагностики (без текста попытки).
ATTEMPT_INSERT_OP = "INSERT OR IGNORE"


def _connect(path: str, *, busy_timeout_ms: int = JOURNAL_BUSY_TIMEOUT_MS
             ) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=max(0.0, int(busy_timeout_ms) / 1000.0),
                           isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=%d" % int(busy_timeout_ms))
    return conn


def _journal_error_detail(error: BaseException | None) -> str:
    """Безопасное описание ошибки журнала: тип, текст SQLite, код.

    В лог уходят только технические атрибуты исключения. Текст ограничен 160
    символами и приведён к одной строке; содержимое попытки (реплики чата,
    ответ провайдера) в диагностику не попадает. Это ровно тот факт, которого
    не хватало в production: раньше писалось лишь имя класса.
    """
    if error is None:
        return "none"
    text = " ".join(str(error).split())
    if len(text) > 160:
        text = text[:157] + "..."
    code = (getattr(error, "sqlite_errorname", None)
            or getattr(error, "sqlite_errorcode", None))
    return "%s: %s%s" % (type(error).__name__, text,
                         " [%s]" % code if code else "")


#: Предел строк, разбираемых из спул-файла за один проход (bounded чтение).
ATTEMPT_SPOOL_MAX_ROWS = 500
#: Порция переноса спула в журнал: bounded работа и память за один шаг.
ATTEMPT_SPOOL_BATCH = 200
#: Сколько порций переносим за один вызов (остальное — следующим вызовом).
ATTEMPT_SPOOL_MAX_BATCHES = 20
#: Потолок строк, удерживаемых процессом, когда недоступны ОБА носителя.
#: Вытеснение самой старой строки сопровождается её полной ERROR-записью:
#: ни одна строка не исчезает анонимно (инвариант D, arch §1).
ATTEMPT_UNPERSISTED_MAX = 200
#: Поля строки попытки, которые переносят носители (спул и аварийный лог) —
#: ровно тот набор, что уже лежит в журнале: новых полей и секретов нет.
SPOOL_FIELDS = ("attempt_id", "chat_id", "job_id", "ts", "stage", "outcome",
                "reason_code", "detail", "limit_source", "limit_value",
                "window_messages")

#: Удержанные строки — ОБЩИЕ на процесс, с ключом по пути файла журнала.
#: `open_ledger` отдаёт НОВЫЙ экземпляр на каждый проход (наблюдатель, `/meme`,
#: отчёты, диагностика), поэтому держатель строки и её переносчик — обычно
#: РАЗНЫЕ объекты одного файла. Список на экземпляре означал бы, что после
#: восстановления носителей строка не доезжает никогда, и единственным следом
#: остаётся ERROR-строка (инвариант D, arch §1).
_UNPERSISTED_BY_PATH: dict[str, list[dict]] = {}
#: Один замок на реестр: списки читают и меняют разные экземпляры и потоки.
_UNPERSISTED_LOCK = threading.Lock()


def _unpersisted_key(path) -> str:
    """Ключ реестра — одна форма пути файла журнала для всех экземпляров."""
    try:
        return os.path.abspath(os.fspath(path))
    except (TypeError, ValueError):
        return str(path)


def held_unpersisted(path) -> list[dict]:
    """Копия строк, удержанных процессом по этому журналу (тесты/наблюдаемость).

    Пустой список значит «удержания нет», а не «носители живы». Копия — чтобы
    вызывающий не мог изменить реестр в обход замка.
    """
    with _UNPERSISTED_LOCK:
        held = _UNPERSISTED_BY_PATH.get(_unpersisted_key(path)) or ()
        return [dict(row) for row in held]


def _parse_spool_row(line: str) -> dict | None:
    """Строка спула → словарь попытки. Мусор/битый JSON → ``None``."""
    text = str(line or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, dict) and parsed.get("attempt_id"):
        return parsed
    return None


def _spool_payload(row: dict) -> dict:
    """Payload строки попытки для носителей — тот же формат, что в спуле.

    Один хелпер на оба места (durable-спул и аварийный ERROR-лог): формат
    записи не дублируется и не изобретается заново.
    """
    source = row if isinstance(row, dict) else {}
    return {key: source.get(key) for key in SPOOL_FIELDS}


#: Одна и та же запись журнала для файлового пути и для единого писателя
#: приложения (`record_attempt_async`): SQL не дублируется, идемпотентность —
#: `INSERT OR IGNORE` по `attempt_id`.
_ATTEMPT_INSERT_SQL = (
    f"INSERT OR IGNORE INTO {ATTEMPT_TABLE} "
    "(attempt_id, chat_id, job_id, ts, stage, outcome, reason_code, detail, "
    "limit_source, limit_value, window_messages) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")


def _attempt_params(row: dict) -> tuple:
    """Параметры `_ATTEMPT_INSERT_SQL` из строки попытки (`SPOOL_FIELDS`)."""
    return (row["attempt_id"], int(row["chat_id"]), row.get("job_id") or "",
            int(row["ts"]), row["stage"], row["outcome"],
            row.get("reason_code") or "", row.get("detail") or "",
            row.get("limit_source") or "", row.get("limit_value"),
            row.get("window_messages"))


class SqliteQuotaLedger:
    """Файловый журнал. Каждый reserve — своё соединение и BEGIN IMMEDIATE.

    Так два потока и два процесса не превышают кап и не списывают один
    job_id дважды. ``apply_schema`` вызывает тест и будущий шаг v40;
    горячий путь таблицу сам не создаёт.
    """

    def __init__(self, path: str, *, writer=None) -> None:
        self.path = str(path)
        #: Асинхронный писатель на соединении приложения (`open_ledger`).
        #: `None` — файловый путь (тесты/файл без DatabaseService).
        self._journal_writer = writer
        #: Удержание живёт НЕ здесь: `open_ledger` создаёт новый экземпляр на
        #: каждый проход, поэтому реестр общий на процесс и ключуется путём
        #: этого файла (`_UNPERSISTED_BY_PATH`).

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

    def slot_delivery(self, chat_id: int, day_bucket: str) -> dict:
        """Слоты суток, разделённые по факту ПОДТВЕРЖДЁННОЙ отправки.

        P0IM-S5B-QUOTA: списание не меняется (слот платный ровно тогда, когда
        провайдер реально вызван — ``COUNTED_STATUSES``), но «израсходовано»
        перестаёт быть неотличимым от «опубликовано». Слот считается
        доставленным, если у его ``job_id`` есть терминальная строка журнала
        попыток с ``outcome='published'``; иначе он попадает в
        ``not_delivered`` с точной причиной закрытия.

        Новых таблиц и колонок нет: оба источника — уже существующие таблицы
        ТОГО ЖЕ файла журнала. Поздняя доставка отложенной строки дописывает
        в журнал `published` с тем же `job_id`, поэтому счётчик сам
        исправляется без отдельного состояния.
        """
        placeholders = ",".join("?" * len(COUNTED_STATUSES))
        conn = _connect(self.path)
        try:
            slots = [str(row["job_id"] or "") for row in conn.execute(
                f"SELECT job_id FROM {RESERVATION_TABLE} "
                f"WHERE chat_id=? AND day_bucket=? AND status IN "
                f"({placeholders})",
                (int(chat_id), day_bucket, *COUNTED_STATUSES)).fetchall()]
            slots = [job for job in slots if job]
            if not slots:
                return {"delivered": 0, "not_delivered": 0, "reasons": {}}
            marks = ",".join("?" * len(slots))
            rows = conn.execute(
                f"SELECT job_id, ts, outcome, reason_code, detail FROM "
                f"{ATTEMPT_TABLE} WHERE job_id IN ({marks}) "
                "ORDER BY ts",
                tuple(slots)).fetchall()
        except Exception:
            logger.warning("[meme] quota slot read failed", exc_info=True)
            return {"delivered": 0, "not_delivered": 0, "reasons": {},
                    "available": False}
        finally:
            conn.close()
        latest: dict[str, dict] = {}
        delivered: set[str] = set()
        for row in rows:
            job = str(row["job_id"] or "")
            if not job:
                continue
            if str(row["outcome"] or "") == "published":
                delivered.add(job)
            latest[job] = dict(row)          # ORDER BY ts → последняя строка
        reasons: dict[str, int] = {}
        not_delivered = 0
        for job in slots:
            if job in delivered:
                continue
            not_delivered += 1
            code = attempt_cause_code(latest.get(job)) or ""
            reasons[code] = reasons.get(code, 0) + 1
        return {"delivered": len(slots) - not_delivered,
                "not_delivered": not_delivered, "reasons": reasons}

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
        """Записать строку попытки. Терминальная попытка НЕ теряется.

        Раньше ошибка `record_attempt` глушилась WARNING'ом: попытка оставалась
        в памяти процесса, а журнал (единственный источник правды для витрины)
        её не видел — отсюда «77 строк за сутки» при 228 реальных.

        Теперь: (1) сначала пробуем дозаписать ранее отложенное (спул и
        удержанные строки); (2) пишем с ОГРАНИЧЕННЫМ числом повторов
        (транзиентная блокировка SQLite); (3) если журнал всё равно недоступен —
        строка уходит в durable-спул рядом с журналом
        (`<db>.attempts.pending.jsonl`) и видна читателю сразу (`attempts()`
        склеивает спул с таблицей); (4) если недоступны ОБА носителя — строка
        удерживается процессом в общем реестре `_UNPERSISTED_BY_PATH` (ключ —
        путь журнала: `open_ledger` отдаёт новый экземпляр на каждый проход,
        поэтому переносит её тот экземпляр, который пишет следующим) и её
        ПОЛНОЕ содержимое уходит в лог
        (инвариант D: потеря не сводится к анонимному предупреждению).
        Новых таблиц и очередей нет.
        """
        self._flush_pending_attempts()
        self._retry_unpersisted()
        last_error: Exception | None = None
        started = time.monotonic()
        for attempt in range(ATTEMPT_WRITE_ATTEMPTS):
            try:
                self._insert_attempt(row)
                return
            except Exception as exc:          # noqa: BLE001 - журнал файловый
                last_error = exc
                if attempt < len(ATTEMPT_WRITE_DELAYS):
                    time.sleep(ATTEMPT_WRITE_DELAYS[attempt])
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if self._spool_attempt(row):
            self._log_journal_fallback(row, last_error, elapsed_ms,
                                       carrier="durable-spool")
            return
        self._hold_unpersisted(row, last_error)

    async def record_attempt_async(self, row: dict) -> None:
        """Записать строку попытки через единого писателя приложения.

        Горячий путь пайплайна: пока чужая транзакция открыта, файловое
        соединение ждало `busy_timeout` (production 13.11.2026 — 15.1 с
        заморозки петли на строку и spool). Единый писатель
        (`DatabaseService.serialized`) ставит `INSERT` в очередь того же
        writer'а, поэтому ожидание асинхронное и заканчивается записью в
        журнал, а не spool. Тот же `INSERT OR IGNORE` в ту же таблицу:
        новых таблиц, очередей и второго журнала нет.

        Писателя нет (тесты/файл без сервиса) или он отказал → прежний
        файловый путь `record_attempt` (retry → durable-спул → удержание).
        """
        self._flush_pending_attempts()
        self._retry_unpersisted()
        if self._journal_writer is None:
            self.record_attempt(row)
            return
        started = time.monotonic()
        try:
            await self._journal_writer(_ATTEMPT_INSERT_SQL, _attempt_params(row))
            return
        except Exception as exc:              # noqa: BLE001 - журнал файловый
            last_error: Exception | None = exc
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if self._spool_attempt(row):
            self._log_journal_fallback(row, last_error, elapsed_ms,
                                       carrier="durable-spool")
            return
        self._hold_unpersisted(row, last_error)

    def _log_journal_fallback(self, row: dict, error: Exception | None,
                              elapsed_ms: int, *, carrier: str) -> None:
        """Строка попытки ушла в durable-носитель — с ТОЧНОЙ причиной.

        Раньше писалось только `error=OperationalError`: ни текста SQLite, ни
        кода, ни операции, ни длительности (production 13.11.2026). Теперь
        причина наблюдаема, а содержимое попытки в лог НЕ попадает.
        """
        logger.warning(
            "[meme] attempt spooled (journal unavailable) | attempt=%s | "
            "carrier=%s | op=%s | table=%s | db=%s | busy_timeout_ms=%d | "
            "elapsed_ms=%d | error=%s",
            str(row.get("attempt_id"))[:12], carrier, ATTEMPT_INSERT_OP,
            ATTEMPT_TABLE, self.path, ATTEMPT_JOURNAL_BUSY_TIMEOUT_MS,
            int(elapsed_ms), _journal_error_detail(error))

    def _hold_unpersisted(self, row: dict, error: Exception | None) -> None:
        """Удержать строку в ОБЩЕМ реестре процесса и записать её ЦЕЛИКОМ в лог.

        Это последний рубеж инварианта D: носителей нет, поэтому факт живёт в
        процессе (реестр на путь журнала, а не на экземпляр: `open_ledger`
        создаёт новый объект каждый проход) до первого освободившегося
        носителя, а в лог уходит ПОЛНАЯ строка (``_spool_payload``:
        attempt_id, outcome, reason_code, detail с ``attempt_mode`` и фактами
        публикации). Потолок списка — ``ATTEMPT_UNPERSISTED_MAX``: вытесняемая
        (самая старая) строка тоже пишется в лог целиком. Замок держится только
        на время правки списка: лог пишется после него.
        """
        row = dict(row)
        attempt_id = str(row.get("attempt_id") or "")
        key = _unpersisted_key(self.path)
        evicted: list[dict] = []
        with _UNPERSISTED_LOCK:
            held = _UNPERSISTED_BY_PATH.setdefault(key, [])
            # Одна и та же строка не удерживается дважды: повтор удержания —
            # это повторная неудача записи того же attempt_id, а не новая
            # попытка.
            if not any(str(item.get("attempt_id") or "") == attempt_id
                       for item in held):
                held.append(row)
            while len(held) > ATTEMPT_UNPERSISTED_MAX:
                evicted.append(held.pop(0))
        for old in evicted:
            self._log_held_row(old, error, note="evicted over cap=%d"
                               % ATTEMPT_UNPERSISTED_MAX)
        self._log_held_row(row, error, note="held")

    def _log_held_row(self, row: dict, error: Exception | None,
                      *, note: str) -> None:
        """Полная строка попытки в лог: JSON без усечения полей и id."""
        try:
            payload = json.dumps(_spool_payload(row), ensure_ascii=False)
        except (TypeError, ValueError):
            payload = json.dumps(_spool_payload(row), ensure_ascii=False,
                                 default=str)
        logger.error(
            "[meme] attempt LOST (journal and spool unavailable) | %s | "
            "error=%s | row=%s", note,
            type(error).__name__ if error is not None else "", payload)

    def _retry_unpersisted(self) -> None:
        """Перенести удержанные строки ЭТОГО журнала в первый ДОСТУПНЫЙ носитель.

        Вызывается в начале `record_attempt` после переноса спула: журнал мог
        освободиться. Строки берутся из ОБЩЕГО реестра по пути файла: держателем
        был, возможно, другой экземпляр (`open_ledger` создаёт новый на каждый
        проход). На каждую строку — одна попытка журнала, при отказе одна
        попытка спула; успех любого носителя убирает строку. За вызов — не
        больше `ATTEMPT_SPOOL_BATCH` строк. Идемпотентность обеспечивает
        `attempt_id` (`INSERT OR IGNORE` и слияние по ключу), поэтому повторный
        перенос не создаёт дубля; замок держится только на снимок и на удаление
        перенесённой строки, не на дисковый ввод-вывод. Никогда не бросает и не
        логирует заново: первая полная запись уже сделана при удержании.
        """
        key = _unpersisted_key(self.path)
        with _UNPERSISTED_LOCK:
            held = _UNPERSISTED_BY_PATH.get(key) or ()
            batch = [dict(row) for row in held[:ATTEMPT_SPOOL_BATCH]]
        if not batch:
            return
        for row in batch:
            try:
                self._insert_attempt(row)
                stored = True
            except Exception:
                stored = self._spool_attempt(row)
            if not stored:
                # Оба носителя всё ещё недоступны: строка остаётся удержанной,
                # следующая попытка — следующим вызовом записи.
                return
            attempt_id = str(row.get("attempt_id") or "")
            with _UNPERSISTED_LOCK:
                left = [item for item in (_UNPERSISTED_BY_PATH.get(key) or ())
                        if str(item.get("attempt_id") or "") != attempt_id]
                if left:
                    _UNPERSISTED_BY_PATH[key] = left
                else:
                    # Пустой список не держим: путь не должен копиться в реестре.
                    _UNPERSISTED_BY_PATH.pop(key, None)

    def merge_terminal_facts(self, chat_id: int, job_id: str,
                             facts: dict) -> bool:
        """Дописать короткие факты в ТЕРМИНАЛЬНУЮ строку существующей попытки.

        P0IM-PB-MANUAL: терминальная строка уже записана пайплайном, поэтому
        снятие маркера ручного приоритета — это аддитивное слияние в её
        ``detail`` JSON, а не вторая строка/колонка/таблица. Терминальная
        строка выбирается тем же порядком ``STAGES``, что у read-model.
        Повторное слияние тех же значений идемпотентно: схема и число строк не
        меняются. Никогда не бросает (диагностика не ломает исход).
        """
        key = str(job_id or "").strip()
        if not key or not isinstance(facts, dict) or not facts:
            return False
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                f"SELECT attempt_id, stage, detail FROM {ATTEMPT_TABLE} "
                "WHERE chat_id=? AND job_id=?",
                (int(chat_id), key)).fetchall()
            if not rows:
                return False
            order = {name: idx for idx, name in enumerate(STAGES)}
            terminal = max(rows, key=lambda row: order.get(
                str(row["stage"]), len(order)))
            merged = parse_attempt_facts(terminal["detail"])
            updated = dict(merged)
            updated.update(facts)
            if updated == merged:
                return True
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                f"UPDATE {ATTEMPT_TABLE} SET detail=? WHERE attempt_id=?",
                (compact_facts(updated), terminal["attempt_id"]))
            conn.execute("COMMIT")
            return True
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.warning("[meme] terminal facts merge failed", exc_info=True)
            return False
        finally:
            conn.close()

    def _insert_attempt(self, row: dict) -> None:
        # Запись под коротким busy_timeout: ожидание чужого писателя не должно
        # замораживать петлю событий (строка всё равно durable-спулится).
        conn = _connect(self.path,
                        busy_timeout_ms=ATTEMPT_JOURNAL_BUSY_TIMEOUT_MS)
        try:
            conn.execute(_ATTEMPT_INSERT_SQL, _attempt_params(row))
        finally:
            conn.close()

    # ── durable-спул непринятых строк (файл рядом с журналом) ──────────────

    def pending_path(self) -> str:
        """Файл спула рядом с журналом (не таблица, не новая БД)."""
        return str(self.path) + ".attempts.pending.jsonl"

    def _spool_attempt(self, row: dict) -> bool:
        """Дописать строку в durable-спул. Возвращает «сохранено ли»."""
        try:
            line = json.dumps(_spool_payload(row), ensure_ascii=False)
            with open(self.pending_path(), "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return True
        except Exception:
            logger.warning("[meme] attempt spool write failed", exc_info=True)
            return False

    def _read_pending(self) -> list[dict]:
        """Строки спула. Битые/чужие строки пропускаются, файл не теряется."""
        path = self.pending_path()
        try:
            if not os.path.exists(path):
                return []
        except OSError:
            return []
        out: list[dict] = []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for index, line in enumerate(handle):
                    if index >= ATTEMPT_SPOOL_MAX_ROWS:
                        break
                    row = _parse_spool_row(line)
                    if row is not None:
                        out.append(row)
        except Exception:
            logger.warning("[meme] attempt spool read failed", exc_info=True)
            return []
        return out

    def _flush_pending_attempts(self) -> None:
        """Перенести спул в журнал порциями. Никогда не бросает.

        Ничего НЕПРОЧИТАННОГО не удаляется: за один шаг читается не больше
        `ATTEMPT_SPOOL_BATCH` строк, а остаток (неудачные вставки + ещё не
        прочитанный хвост) переписывается обратно ДО удаления исходного файла.
        Запись идемпотентна (`INSERT OR IGNORE` по `attempt_id`), поэтому
        повторный перенос после сбоя не создаёт дублей.
        """
        for _ in range(ATTEMPT_SPOOL_MAX_BATCHES):
            if not self._flush_pending_batch():
                return

    def _flush_pending_batch(self) -> bool:
        """Один ограниченный шаг переноса. True — остались ещё строки."""
        path = self.pending_path()
        try:
            if not os.path.exists(path):
                return False
        except OSError:
            return False
        failed: list[dict] = []
        offset = 0
        drained = False
        last_error: Exception | None = None
        try:
            with open(path, "rb") as handle:
                for _ in range(ATTEMPT_SPOOL_BATCH):
                    line = handle.readline()
                    if not line:
                        drained = True
                        break
                    # Байтовое смещение: точная граница прочитанного префикса.
                    offset = handle.tell()
                    row = _parse_spool_row(line.decode("utf-8", "replace"))
                    if row is None:
                        continue
                    try:
                        self._insert_attempt(row)
                    except Exception as exc:   # noqa: BLE001 - журнал файловый
                        # Первая же неудача = журнал недоступен. Продолжать
                        # нельзя: каждая следующая попытка — ещё один
                        # busy_timeout в петле событий (до 200 × 5 с).
                        failed.append(row)
                        last_error = exc
                        break
        except OSError:
            logger.warning("[meme] attempt spool read failed", exc_info=True)
            return False
        if drained and not failed:
            try:
                os.remove(path)
            except OSError:
                logger.warning("[meme] attempt spool remove failed",
                               exc_info=True)
            return False
        if failed:
            # Журнал недоступен: не крутимся в цикле, остаток сохраняем целиком.
            logger.warning(
                "[meme] attempt spool not drained (journal unavailable) | "
                "failed=%d | op=%s | table=%s | db=%s | busy_timeout_ms=%d | "
                "error=%s", len(failed), ATTEMPT_INSERT_OP, ATTEMPT_TABLE,
                self.path, ATTEMPT_JOURNAL_BUSY_TIMEOUT_MS,
                _journal_error_detail(last_error))
        temp_path = path + ".tmp"
        try:
            with open(path, "rb") as src, open(temp_path, "wb") as dst:
                # Остаток = неудачные строки (они старше) + непрочитанный хвост.
                for row in failed:
                    dst.write((json.dumps(row, ensure_ascii=False) + "\n")
                              .encode("utf-8"))
                src.seek(offset)
                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
            os.replace(temp_path, path)
        except Exception:
            logger.warning("[meme] attempt spool rewrite failed", exc_info=True)
            try:
                os.remove(temp_path)
            except OSError:
                pass
            return False
        return not failed

    def attempts(self, chat_id: int | None, *, limit: int = 20) -> list[dict]:
        """Строки журнала + ещё не перенесённый спул (одна правда для витрины).

        Спул склеивается с таблицей по `attempt_id`, поэтому строка, которую
        журнал не принял, всё равно видна читателю — и не исчезает из «77/24ч».
        """
        self._flush_pending_attempts()
        merged: dict[str, dict] = {}
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
            for row in rows:
                item = dict(row)
                merged[str(item.get("attempt_id"))] = item
        except Exception as exc:              # noqa: BLE001 - журнал файловый
            # Витрина продолжает работать по спулу, но причина отказа чтения
            # журнала должна быть видна (раньше исключение глоталось молча).
            logger.warning(
                "[meme] attempt journal read failed | op=SELECT | table=%s | "
                "db=%s | error=%s", ATTEMPT_TABLE, self.path,
                _journal_error_detail(exc))
        finally:
            conn.close()
        for row in self._read_pending():
            try:
                if chat_id is not None and int(row.get("chat_id") or 0) != \
                        int(chat_id):
                    continue
            except (TypeError, ValueError):
                continue
            merged.setdefault(str(row.get("attempt_id")), row)
        out = list(merged.values())
        out.sort(key=lambda item: _as_int(item.get("ts"), 0), reverse=True)
        return out[:int(limit)]


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
            # Нет журнала — нет и фактов доставки: `None`, а не «0 отправлено».
            "delivered": None,
            "not_delivered": None,
            "not_delivered_reasons": {},
        }
    counts = ledger.status_counts(chat_id, day.bucket)
    spent = sum(counts.get(status, 0) for status in COUNTED_STATUSES)
    remaining = max(0, int(limit) - spent) if int(limit) > 0 else 0
    # P0IM-S5B-QUOTA: «израсходовано» и «отправлено» — РАЗНЫЕ факты. Слот,
    # списанный под попытку без доставки, не возвращается (деньги за вызов
    # провайдера уже потрачены, и возврат слота разрешил бы лишний платный
    # вызов сверх суточного капа), но и не выдаётся за публикацию.
    slots = ledger.slot_delivery(chat_id, day.bucket)
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
        "delivered": slots.get("delivered"),
        "not_delivered": slots.get("not_delivered"),
        "not_delivered_reasons": dict(slots.get("reasons") or {}),
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


@dataclass
class RunTrace:
    """Идентичность и МЕСТО текущей попытки (P0IM-D7 / S5-MEME).

    Живёт рядом с самой попыткой и обновляется по ходу: ``job_id`` mint-ится
    до первого гейта, ``stage`` — реальный этап, на котором попытка находится
    сейчас. По этой трассе пишется терминальная строка при ОБРЫВЕ процесса,
    когда обычный возврат результата уже невозможен.

    ``counters``/``facts`` — те же изменяемые словари, что пишет сама попытка:
    запись об обрыве видит РЕАЛЬНО пройденные этапы, а не догадку о них.
    """

    chat_id: int = 0
    job_id: str = ""
    stage: str = STAGE_CONSIDERED
    now_ts: int = 0
    counters: dict = field(default_factory=dict)
    facts: dict = field(default_factory=dict)
    settings: "MemeSettings | None" = None
    ledger: Any = None
    manual: bool = False
    #: Изображение уже ушло в чат (sender подтвердил отправку). Отмена после
    #: этого — публикация, а не провал.
    delivered: bool = False


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


def attempt_mode_of(facts: dict | None) -> str:
    """Режим ПОПЫТКИ из фактов ТЕРМИНАЛЬНОЙ строки: `manual`|`auto`|`""`.

    Читается только точный ключ `attempt_mode`, затем контрактный `mode`.
    Вызывать ТОЛЬКО для терминальной строки: у этапа «прикол» ключ `mode`
    занят бюджетом длины (`auto`/`fixed`) и режимом попытки не является.
    """
    data = facts if isinstance(facts, dict) else {}
    raw = str(data.get("attempt_mode") or data.get("mode") or "")
    if raw == "manual":
        return "manual"
    if raw in ("automatic", "auto"):
        return "auto"
    return ""


def _looks_like_cause_code(text: str) -> bool:
    """Похоже ли значение на КОД причины, а не на человеческую фразу.

    `detail` терминальной строки хранит либо код (`publisher_not_bound`,
    `chat_gate_disabled`, `tg:123` — с `:` не подходит), либо готовый текст
    (`module_disabled_during_generation`). Кодами считаем только строчную
    латиницу/цифры/подчёркивания: так в витрину не уезжает пересказ.
    """
    token = str(text or "")
    if not 3 <= len(token) <= 48:
        return False
    if not token.isascii() or not token[0].islower() or not token[0].isalpha():
        return False
    return all(ch.islower() or ch.isdigit() or ch == "_" for ch in token)


def attempt_cause_code(row: dict | None) -> str:
    """ТОЧНЫЙ код причины закрытия попытки (для витрины доставки и квоты).

    `reason_code` строки — общий код исхода (`publish_blocked`), а конкретная
    причина лежит в фактах терминальной строки (`detail`): именно там живёт
    `publisher_not_bound`. Пустой/непохожий на код `detail` не подставляется —
    тогда возвращается сам `reason_code`.
    """
    data = row if isinstance(row, dict) else {}
    reason = str(data.get("reason_code") or "")
    try:
        facts = parse_attempt_facts(data)
    except Exception:                        # pragma: no cover - defensive
        facts = {}
    for candidate in (facts.get("detail"),
                      (facts.get("publication") or {}).get("detail")
                      if isinstance(facts.get("publication"), dict) else None):
        text = str(candidate or "").strip()
        if _looks_like_cause_code(text):
            return text
    return reason


def _attempt_rows(result: AttemptResult, *, now_ts: int,
                  settings: MemeSettings) -> list[dict]:
    """Строки журнала одной попытки: по строке на пройденный этап + терминал.

    ``stage_facts["events"]`` — НЕ этап, а цепочка событий §1.3: она
    дописывается в терминальную строку, а человеческий ``detail`` (код/факт
    причины) сохраняется ВНУТРИ её JSON ключом ``detail``. Так «генерация
    прошла» и «отправка прошла» остаются различимыми в одной строке журнала.
    """
    stages = [stage for stage in STAGES
              if int((result.counters or {}).get(stage) or 0)]
    if result.stage in stages:
        stages.remove(result.stage)
    # Терминальная строка — РЕАЛЬНЫЙ итоговый этап попытки (`result.stage`), а
    # не последний счётчик: иначе причина/факты/события уезжали в строку
    # «skipped», а строка «publish» оставалась без факта доставки.
    stages.append(result.stage)
    events = (result.stage_facts or {}).get("events")
    rows: list[dict] = []
    for stage in stages:
        terminal = stage == stages[-1]
        payload = dict((result.stage_facts or {}).get(stage) or {})
        if terminal:
            if events:
                payload["events"] = [dict(item) for item in events
                                     if isinstance(item, dict)]
            if result.detail:
                payload["detail"] = str(result.detail)
            # §3 (P0 corrective): режим попытки — в СУЩЕСТВУЮЩЕМ detail JSON
            # терминальной строки. `manually_triggered` есть на результате, но
            # в журнал не попадал, поэтому read-model брал mode из позднего
            # publication-факта (его нет у раннего отказа).
            #
            # Ключ `attempt_mode` — ТОЧНЫЙ режим попытки; `mode` пишется рядом
            # для §1-контракта, но у этапа «прикол» этот же ключ занимает
            # бюджет длины (`auto`/`fixed`). Читатели берут режим ТОЛЬКО из
            # терминальной строки и предпочитают `attempt_mode`, поэтому
            # бюджетная подпись прикола не может выдать себя за режим попытки.
            attempt_mode = (MODE_MANUAL if result.manually_triggered
                            else MODE_AUTOMATIC)
            payload["attempt_mode"] = attempt_mode
            payload.setdefault("mode", attempt_mode)
            # P0IM-PB-ID (S4-корректива): факты ПУБЛИКАЦИИ (источник, бронь,
            # права, `output.tg_message_id`) — часть итога попытки, а не
            # отдельного этапа. Раньше они терялись: `_finish` писал только
            # payload своего этапа, поэтому в терминальной строке не было
            # ключа `publication`, fallback read-model был мёртв, и карточка
            # показывала `message_id: null` при `delivered: true`.
            publication = (result.stage_facts or {}).get("publication")
            if isinstance(publication, dict) and publication:
                payload["publication"] = dict(publication)
        facts = compact_facts(payload)
        # Терминальная строка несёт факты (вместе с кодом причины внутри
        # JSON); пройденные этапы — свой JSON фактов.
        detail = (facts or result.detail) if terminal else facts
        outcome = (result.outcome if terminal
                   else ("skipped" if stage == STAGE_SKIPPED else "passed"))
        row = {
            "attempt_id": uuid.uuid4().hex,
            "chat_id": int(result.chat_id),
            "job_id": result.job_id,
            "ts": int(now_ts),
            "stage": stage,
            "outcome": outcome,
            "reason_code": result.reason if terminal else "",
            "detail": detail,
            "limit_source": result.limit.source if result.limit else "",
            "limit_value": (result.limit.ceiling if result.limit else None),
            "window_messages": settings.window_messages,
        }
        _remember(row)
        rows.append(row)
    return rows


def _finish(result: AttemptResult, *, ledger, now_ts: int,
            settings: MemeSettings) -> AttemptResult:
    """Записать журнал попытки синхронно (файловый путь / отмена).

    Горячий путь пайплайна идёт через `_finish_async`: там запись идёт
    единым писателем приложения и не ждёт лок в петле событий.
    """
    for row in _attempt_rows(result, now_ts=now_ts, settings=settings):
        if ledger is not None:
            try:
                ledger.record_attempt(row)
            except Exception:
                logger.warning("[meme] attempt journal failed", exc_info=True)
    result.window_messages = settings.window_messages
    return result


async def _finish_async(result: AttemptResult, *, ledger, now_ts: int,
                        settings: MemeSettings) -> AttemptResult:
    """Записать журнал попытки через единого писателя приложения.

    Строки те же (`_attempt_rows`), `INSERT` тот же (`INSERT OR IGNORE` по
    `attempt_id`), но запись сериализуется с остальными писателями
    `DatabaseService`: ожидание чужой транзакции — асинхронное, без
    `busy_timeout` в петле событий (production 13.11.2026: 15.1 с заморозки
    на строку и spool).
    """
    writer = getattr(ledger, "record_attempt_async", None)
    for row in _attempt_rows(result, now_ts=now_ts, settings=settings):
        if ledger is None:
            continue
        try:
            if callable(writer):
                await writer(row)
            else:                            # чужой ledger (тесты/стабы)
                ledger.record_attempt(row)
        except Exception:
            logger.warning("[meme] attempt journal failed", exc_info=True)
    result.window_messages = settings.window_messages
    return result


def record_run_interrupted(trace: RunTrace) -> AttemptResult:
    """Терминальная запись ОБРЫВА попытки (рестарт сервиса/отмена процесса).

    Пишет ТУ ЖЕ строку журнала, что и любой терминальный исход, с реальным
    этапом остановки (``trace.stage``) и причиной ``run_interrupted``: вместо
    «попытка не запускалась» в трассе появляется «остановилась на шаге …».
    Идентичность (``job_id``) — та, что попытка уже получила, поэтому строка
    склеивается с остальными строками этого же запуска.

    Ничего не бросает: запись об обрыве не подменяет саму отмену и не мешает
    остановке процесса. ``CancelledError`` внутри неё не глотается — здесь нет
    ни одного ``await``, только один стейтмент журнала.
    """
    chat_id = int(trace.chat_id or 0)
    counters = dict(trace.counters or {})
    facts = dict(trace.facts or {})
    settings = trace.settings if isinstance(trace.settings, MemeSettings) \
        else MemeSettings()
    if trace.delivered:
        # Картинка уже доставлена: обрыв после отправки — публикация, а не
        # провал. Выдавать «не отправлено» за правду нельзя.
        counters[STAGE_PUBLISH] = max(1, int(counters.get(STAGE_PUBLISH) or 0))
        publish_facts = facts.get(STAGE_PUBLISH)
        if not isinstance(publish_facts, dict):
            publish_facts = {}
            facts[STAGE_PUBLISH] = publish_facts
        publish_facts["delivery"] = "sent"
        result = AttemptResult(
            chat_id=chat_id, stage=STAGE_PUBLISH, outcome="published",
            reason="sent", detail="sent_before_cancellation",
            job_id=trace.job_id, published=True, generated=True,
            counters=counters, stage_facts=facts,
            manually_triggered=bool(trace.manual))
    else:
        result = AttemptResult(
            chat_id=chat_id, stage=str(trace.stage or STAGE_CONSIDERED),
            outcome="failed", reason=REASON_RUN_INTERRUPTED,
            detail="process_cancelled", job_id=trace.job_id,
            counters=counters, stage_facts=facts,
            manually_triggered=bool(trace.manual))
    try:
        _finish(result, ledger=trace.ledger, now_ts=int(trace.now_ts or 0),
                settings=settings)
    except Exception:
        logger.warning("[meme] interrupted attempt journaling failed",
                       exc_info=True)
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


# ── снапшот источника и его содержательная перепроверка (§1.2 P0) ───────────
#: Предел числа id в одном IN(...)-запросе проверки исходных сообщений.
SOURCE_CHECK_CHUNK = 400


@dataclass(frozen=True)
class SourceSnapshot:
    """Входной материал КОНКРЕТНОГО мема, зафиксированный на старте генерации.

    Это не требование «чат замер» (§1.2.1): новые сообщения, реакции,
    ``latest_message_id`` и движение общего watermark снапшот не ломают и
    публикацию не отменяют. Снапшот нужен, чтобы (а) знать, из чего именно
    сделан мем, и (б) отличить реальную утрату валидности (исходные сообщения
    удалены) от обычного роста переписки.
    """

    chat_id: int
    run_id: str
    mode: str
    purpose: str
    request_ref: str
    message_ids: tuple[int, ...]
    message_count: int
    first_id: int | None
    last_id: int | None
    digest: str
    captured_at: int

    def as_dict(self) -> dict:
        """Durable-вид (R17-safe): id/числа/коды, без текстов сообщений."""
        return {
            "chat_id": int(self.chat_id),
            "run_id": str(self.run_id),
            "mode": str(self.mode),
            "purpose": str(self.purpose),
            "request_ref": str(self.request_ref),
            "message_count": int(self.message_count),
            "first_id": self.first_id,
            "last_id": self.last_id,
            "digest": str(self.digest),
            "captured_at": int(self.captured_at),
        }


def _message_ids(rows) -> tuple[int, ...]:
    """id строк окна по возрастанию (без чужих чатов и без дублей)."""
    ids: list[int] = []
    for row in rows or ():
        try:
            value = int(row.get("id"))
        except (TypeError, ValueError, AttributeError):
            continue
        if value not in ids:
            ids.append(value)
    ids.sort()
    return tuple(ids)


def build_source_snapshot(*, chat_id: int, rows, run_id: str, mode: str,
                          purpose: str, request_ref: str = "",
                          now_ts: int) -> SourceSnapshot:
    """Зафиксировать источник мема: чат, run, сообщения/версии, цель, режим."""
    ids = _message_ids(rows)
    digest = hashlib.sha256()
    for row in rows or ():
        try:
            text = str(row.get("text") or "")
        except Exception:
            text = ""
        digest.update(f"{row.get('id')}:{_text_sha12(text)}\n".encode("utf-8"))
    return SourceSnapshot(
        chat_id=int(chat_id), run_id=str(run_id),
        mode=str(mode), purpose=str(purpose),
        request_ref=str(request_ref or ""),
        message_ids=ids, message_count=len(ids),
        first_id=(ids[0] if ids else None),
        last_id=(ids[-1] if ids else None),
        digest=digest.hexdigest()[:16], captured_at=int(now_ts))


def _row_int(row, key: str) -> int:
    """Число из строки результата SQL (Row/dict), 0 при отсутствии."""
    if row is None:
        return 0
    try:
        value = row.get(key) if isinstance(row, dict) else row[key]
    except Exception:
        return 0
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


async def _default_source_check(db, chat_id: int, snapshot: SourceSnapshot
                                ) -> tuple[bool, str, str]:
    """Есть ли ещё исходный материал мема? ``(ok, код, detail)``.

    Проверяется РОВНО факт «сообщения снапшота ещё существуют». Недоказуемые
    вещи не блокируют: нет БД, пустой снапшот или ошибка чтения → ``ok``
    (готовый мем не отменяется по догадке). Отмена возможна только когда
    доказано, что НИ ОДНОГО исходного сообщения не осталось.
    """
    if db is None or not snapshot.message_ids:
        return True, "", ""
    raw = getattr(db, "db", db)
    try:
        remaining = 0
        for start in range(0, len(snapshot.message_ids), SOURCE_CHECK_CHUNK):
            chunk = snapshot.message_ids[start:start + SOURCE_CHECK_CHUNK]
            placeholders = ",".join("?" for _ in chunk)
            cursor = await raw.execute(
                "SELECT COUNT(*) AS c FROM smart_messages "
                f"WHERE chat_id = ? AND id IN ({placeholders})",
                (int(chat_id), *chunk))
            remaining += _row_int(await cursor.fetchone(), "c")
    except Exception:
        logger.debug("[meme] source check unreadable — не блокируем",
                     exc_info=True)
        return True, "", ""
    if remaining > 0:
        return True, "", ""
    return False, SKIP_SOURCE_GONE, "source_messages_deleted"


# ── B2: реальные права на публикацию (не мок гейта) ─────────────────────────
async def _default_rights_check(db, chat_id: int) -> tuple[bool, str, str]:
    """Допустима ли публикация в этом чате ПРЯМО СЕЙЧАС? ``(ok, код, detail)``.

    Проверка идёт по РЕАЛЬНОМУ ростору кандидатов механизма
    (``_candidate_chat_ids``: PG ``chat_profiles`` либо durable SQLite-список
    ``smart_messages``), а не по синтетической строке контекста. Именно это
    отличает настоящую перепроверку прав от мока publish-гейта (B2).

    Недоказуемое не блокирует: нет БД/источник не читается → ``ok`` (готовый
    мем не отменяется по догадке). Отказ возможен только когда ростер
    прочитан и чата в нём нет.
    """
    if db is None:
        return True, "", "roster_unavailable"
    try:
        ids = await _candidate_chat_ids(db)
    except Exception:
        logger.debug("[meme] rights roster unreadable — не блокируем",
                     exc_info=True)
        return True, "", "roster_unavailable"
    try:
        present = int(chat_id) in {int(item) for item in ids}
    except (TypeError, ValueError):
        return True, "", "roster_unavailable"
    if present:
        return True, "", ""
    return False, SKIP_RIGHTS_REVOKED, "chat_not_in_roster"


# ── B1 (arch/deferred-publication.md): durable доставка готового артефакта ───
#: Значение колонки `task_jobs.kind` для отложенного мема. Схема НЕ меняется:
#: используется существующая таблица v14 (`coalesce_key` + unique partial на
#: активных статусах), как у `vision.pending_intent`/`initiative.observe`.
DEFERRED_KIND = "meme.pending_publish"
DEFERRED_OWNER = "meme.initiative"
DEFERRED_COALESCE_PREFIX = "meme:pending_publish:"


def deferred_coalesce_key(chat_id: int) -> str:
    """Одна активная отложенная запись на чат (unique partial v14)."""
    return f"{DEFERRED_COALESCE_PREFIX}{int(chat_id)}"


def deferred_dir() -> Path:
    """Managed-каталог байтов отложенных мемов (env-override допустим).

    Прецедент — `services/cover_style_assets.py`: метаданные в БД, байты НЕ в
    БД, каталог вне git-дерева деплоя (`var/`), чтобы `git pull --ff-only` не
    пачкал рабочее дерево.
    """
    raw = os.getenv("MEME_PENDING_DIR", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[1] / "var" / "meme_pending"


def deferred_file(job_id: str) -> Path:
    return deferred_dir() / f"{str(job_id)}.bin"


def save_deferred_artifact(job_id: str, content) -> dict:
    """Записать байты готового мема: temp-файл → `os.replace`, режим 0600.

    Атомарность обязательна: читатель не должен увидеть половину файла, а
    падение процесса посреди записи не должно оставить «готовый» артефакт.
    """
    data = bytes(content or b"")
    directory = deferred_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = deferred_file(job_id)
    handle_fd, temp_path = tempfile.mkstemp(
        dir=str(directory), prefix=".pending-", suffix=".tmp")
    try:
        with os.fdopen(handle_fd, "wb") as handle:
            handle.write(data)
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass                      # Windows/ФС без POSIX-режимов
        os.replace(temp_path, target)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
    return {"path": str(target), "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data)}


def load_deferred_bytes(row: dict) -> bytes | None:
    """Байты отложенного мема по `result_ref`. Нет файла → None (не гадаем)."""
    raw = str((row or {}).get("result_ref") or "")
    if not raw:
        # Страховка: путь мог остаться только в payload (сбой UPDATE колонки).
        raw = str(deferred_payload(row).get("path") or "")
    if not raw:
        return None
    try:
        return Path(raw).read_bytes()
    except OSError:
        return None


def remove_deferred_bytes(result_ref) -> bool:
    """Удалить файл артефакта (терминальный переход). Идемпотентно."""
    raw = str(result_ref or "")
    if not raw:
        return False
    try:
        Path(raw).unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        logger.warning("[meme] deferred artifact not removed | path=%s", raw)
        return False


def deferred_retention_seconds(cfg) -> int:
    """Ретенция отложенного артефакта = собственный кулдаун механизма.

    Новых сроков не вводится (архитектурное решение §6): значение уже
    существует и настраивается владельцем. Кулдаун ≤ 0 не даёт «мгновенно
    мёртвого» артефакта — берётся существующий заводской дефолт.
    """
    value = int(getattr(cfg, "cooldown_seconds", 0) or 0)
    return value if value > 0 else DEFAULT_COOLDOWN_SECONDS


def _task_store(db):
    """`TaskJobStore` для существующей таблицы `task_jobs` (или None).

    Полноценный `DatabaseService` нужен только durable-пути: диагностические
    прогоны с урезанной БД откладывание не поддерживают (и не выдают его за
    поддержанное).
    """
    if db is None or getattr(db, "db", None) is None:
        return None
    if getattr(db, "write_transaction", None) is None:
        return None
    try:
        from services.task_supervisor import TaskJobStore
    except Exception:
        logger.warning("[meme] task_jobs store unavailable", exc_info=True)
        return None
    return TaskJobStore(db)


async def _deferred_rows(db, chat_id: int | None = None, *,
                        include_stale: bool = False) -> list[dict]:
    """Активные (и при нужде прерванные) отложенные записи.

    Одна активная строка на чат гарантируется unique partial-индексом v14;
    `interrupted` в индекс не входит, поэтому прерванная запись не мешает
    новой, но обязана получить честный терминальный исход (иначе файл и
    строка висели бы вечно).
    """
    if db is None or getattr(db, "db", None) is None:
        return []
    from services.task_supervisor import JOB_INTERRUPTED, JOB_QUEUED, JOB_RUNNING
    statuses = [JOB_QUEUED, JOB_RUNNING]
    if include_stale:
        statuses.append(JOB_INTERRUPTED)
    placeholders = ",".join("?" for _ in statuses)
    sql = ("SELECT * FROM task_jobs WHERE kind = ? AND status IN ("
           + placeholders + ")")
    params: list = [DEFERRED_KIND, *statuses]
    if chat_id is not None:
        sql += " AND coalesce_key = ?"
        params.append(deferred_coalesce_key(int(chat_id)))
    sql += " ORDER BY created_at"
    try:
        cursor = await db.db.execute(sql, tuple(params))
        return [dict(row) for row in await cursor.fetchall()]
    except Exception:
        logger.debug("[meme] deferred rows unreadable", exc_info=True)
        return []


async def deferred_active_row(db, chat_id: int) -> dict | None:
    """Есть ли в чате уже отложенный (ещё не доставленный) мем."""
    rows = await _deferred_rows(db, int(chat_id))
    return rows[0] if rows else None


def deferred_payload(row: dict) -> dict:
    """Разобрать payload строки `task_jobs` (не JSON → пустой словарь)."""
    raw = row.get("payload") if isinstance(row, dict) else None
    if isinstance(raw, dict):
        return dict(raw)
    text = str(raw or "").strip()
    if not text.startswith("{"):
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def deferred_wait_result(chat_id: int, row: dict, *, ts: int | None = None
                         ) -> AttemptResult:
    """Результат «ждём отложенный артефакт» — БЕЗ записи в журнал попыток.

    Ожидание не является попыткой отправки: писать по строке на проход
    означало бы фальшивую активность (12 строк/час). Состояние ожидания видно
    в `task_jobs` (`attempt`, `reason_code`) и в состоянии прохода.
    """
    payload = deferred_payload(row)
    job_id = str(row.get("job_id") or "")
    return AttemptResult(
        chat_id=int(chat_id), stage=STAGE_PUBLISH, outcome="skipped",
        reason=SKIP_PUBLICATION_CONFLICT, detail="deferred_pending",
        job_id=str(payload.get("run_id") or job_id), generated=False,
        published=False,
        counters={STAGE_CONSIDERED: 1, STAGE_PUBLISH: 1},
        stage_facts={"publication": {
            "deferred": {"job_id": job_id,
                         "run_id": str(payload.get("run_id") or ""),
                         "attempt": int(row.get("attempt") or 0),
                         "expires_at": int(payload.get("expires_at") or 0),
                         "awaiting_slot": True},
            # Мем не привязан к intent-записи: фиксируем N/A с причиной (B2).
            "intent_lifecycle": {"status": "n/a",
                                 "reason": "meme_has_no_intent_binding"}}},
        manually_triggered=False)


async def defer_generated_meme(db, *, chat_id: int, content, snapshot,
                               run_id: str, reason: str, detail: str,
                               cfg, prompt_origin: str, now_ts: int) -> dict | None:
    """Сохранить готовый авто-мем, которому не досталось слота публикации.

    Возвращает компактные факты для журнала/диагностики либо ``None``, если
    durable-путь недоступен (тогда поведение честно остаётся прежним).
    Байты пишутся ДО строки очереди: если запись файла не удалась, откладывать
    нечего и мы не выдаём «сохранено» за сохранённое.
    """
    store = _task_store(db)
    if store is None:
        return None
    retention = deferred_retention_seconds(cfg)
    job_id = uuid.uuid4().hex
    try:
        stored = save_deferred_artifact(job_id, content)
    except Exception:
        logger.warning("[meme] deferred artifact save failed | chat=%s",
                       chat_id, exc_info=True)
        return None
    payload = {
        "chat_id": int(chat_id),
        "run_id": str(run_id),
        "created_at": int(now_ts),
        "expires_at": int(now_ts) + int(retention),
        "sha256": str(stored["sha256"]),
        "size": int(stored["size"]),
        "mime": "image/png",
        "deferred_reason": str(reason),
        "deferred_detail": str(detail or ""),
        "msg_ids": [int(item) for item in (snapshot.message_ids
                                           if snapshot is not None else ())],
        "msg_count": int(snapshot.message_count if snapshot is not None else 0),
        "first_id": (snapshot.first_id if snapshot is not None else None),
        "last_id": (snapshot.last_id if snapshot is not None else None),
        "snapshot_digest": str(snapshot.digest if snapshot is not None else ""),
        "prompt_origin": str(prompt_origin or ""),
        "purpose": PURPOSE_AUTOMATIC,
        "mode": MODE_AUTOMATIC,
    }
    try:
        queued_id = await store.enqueue(
            owner=DEFERRED_OWNER, kind=DEFERRED_KIND,
            coalesce_key=deferred_coalesce_key(int(chat_id)),
            payload=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            deadline_at=int(payload["expires_at"]), job_id=job_id)
    except Exception:
        logger.warning("[meme] deferred enqueue failed | chat=%s", chat_id,
                       exc_info=True)
        remove_deferred_bytes(stored["path"])
        return None
    if str(queued_id) != job_id:
        # В чате уже есть активный отложенный мем: второй не ставим (одна
        # строка на чат). Свежий файл не теряем молча — удаляем дубль, старый
        # артефакт остаётся в очереди.
        remove_deferred_bytes(stored["path"])
        return {"job_id": str(queued_id), "already_pending": True,
                "reason": str(reason), "detail": str(detail or "")}
    # `result_ref` (путь байтов) — существующая колонка очереди: указываем её
    # после enqueue, чтобы строка без файла и файл без строки не разъезжались.
    try:
        async def _set_ref(conn):
            return await conn.execute(
                "UPDATE task_jobs SET result_ref = ? WHERE job_id = ?",
                (str(stored["path"]), job_id))

        await db.write_transaction(_set_ref, op_name="meme_deferred_ref")
    except Exception:
        logger.warning("[meme] deferred result_ref not set | job=%s", job_id,
                       exc_info=True)
    return {"job_id": job_id, "path": str(stored["path"]),
            "sha256": str(stored["sha256"]), "size": int(stored["size"]),
            "expires_at": int(payload["expires_at"]),
            "retention_seconds": int(retention), "reason": str(reason),
            "detail": str(detail or "")}


async def deliver_deferred(db, chat_id: int, *, ledger=None, sender=None,
                           publish_gate=None, publication=None,
                           claim_store=None, chat_enabled=None,
                           initiative_enabled=None, settings=None,
                           now: datetime | None = None,
                           now_ts: int | None = None,
                           tz_name: str | None = None,
                           tz_source: str | None = None,
                           rights_check=None,
                           source_check=None) -> AttemptResult | None:
    """Одна попытка доставки отложенного мема чата (существующий тик мема).

    Возвращает результат ТЕРМИНАЛЬНОГО перехода (строка журнала ровно одна
    на переход) либо ``None``, если доставлять нечего или слот занят —
    ожидание строк журнала не пишет.
    """
    rows = await _deferred_rows(db, int(chat_id), include_stale=True)
    if not rows:
        return None
    cfg = settings if isinstance(settings, MemeSettings) else \
        await load_settings(chat_id)
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    ts = int(now_ts if now_ts is not None else stamp.timestamp())
    day = day_window(chat_id, stamp, tz_name=tz_name, tz_source=tz_source)
    result = None
    for row in rows:
        outcome = await _deliver_deferred_row(
            db, row, cfg=cfg, stamp=stamp, ts=ts, day=day, ledger=ledger,
            sender=sender, publish_gate=publish_gate, publication=publication,
            claim_store=claim_store, chat_enabled=chat_enabled,
            initiative_enabled=initiative_enabled, rights_check=rights_check,
            source_check=source_check)
        if outcome is not None:
            result = outcome
    return result


async def deliver_deferred_all(db, *, chat_ids=None, **kwargs
                               ) -> list[AttemptResult]:
    """Перебрать ВСЕ активные отложенные мемы (не зависит от ротации ростера).

    `chat_ids` — не фильтр доставки, а подсказка порядка: «голодный» чат не
    должен ждать неделями только потому, что не попал в текущий проход.
    """
    rows = await _deferred_rows(db, None, include_stale=True)
    if not rows:
        return []
    order: list[int] = []
    for item in chat_ids or ():
        try:
            order.append(int(item))
        except (TypeError, ValueError):
            continue
    seen: list[int] = []
    for row in rows:
        payload = deferred_payload(row)
        try:
            chat_id = int(payload.get("chat_id"))
        except (TypeError, ValueError):
            continue
        if chat_id not in seen:
            seen.append(chat_id)
    seen.sort(key=lambda cid: (order.index(cid) if cid in order
                               else len(order), cid))
    results: list[AttemptResult] = []
    for chat_id in seen:
        try:
            result = await deliver_deferred(db, chat_id, **kwargs)
        except Exception:
            logger.warning("[meme] deferred delivery raised | chat=%s",
                           chat_id, exc_info=True)
            continue
        if result is not None:
            results.append(result)
    return results


async def _deliver_deferred_row(db, row: dict, *, cfg: MemeSettings,
                                stamp: datetime, ts: int, day: DayWindow,
                                ledger=None, sender=None, publish_gate=None,
                                publication=None, claim_store=None,
                                chat_enabled=None, initiative_enabled=None,
                                rights_check=None,
                                source_check=None) -> AttemptResult | None:
    """Стражи → CAS → бронь → отправка готового артефакта (без генерации).

    Порядок — как в `arch/deferred-publication.md` §5: сначала дешёвые
    содержательные проверки, дорогое (бронь/sender) — в конце. Никаких
    повторных вызовов LLM/провайдера здесь нет и быть не может: байты уже
    существуют, а здоровье image-backend не перепроверяется (это была бы
    потеря оплаченного артефакта).
    """
    from services.task_supervisor import (JOB_CANCELLED, JOB_COMPLETED,
                                          JOB_FAILED, JOB_INTERRUPTED)
    store = _task_store(db)
    if store is None:
        return None
    job_id = str(row.get("job_id") or "")
    status = str(row.get("status") or "")
    payload = deferred_payload(row)
    result_ref = str(row.get("result_ref") or "")
    try:
        chat_id = int(payload.get("chat_id"))
    except (TypeError, ValueError):
        chat_id = 0
    if not job_id or not chat_id:
        logger.warning("[meme] deferred row without chat | job=%s", job_id)
        return None
    run_id = str(payload.get("run_id") or job_id)
    expires_at = int(payload.get("expires_at")
                     or row.get("deadline_at") or 0)

    events: list[dict] = []
    facts: dict = {"events": events, STAGE_PUBLISH: {}}

    def emit(name: str, *, reason: str = "", detail: str = "",
             delivered: bool | None = None) -> None:
        if len(events) >= MAX_EVENTS_PER_ATTEMPT:
            return
        item = {"name": str(name), "at": int(ts), "run_id": run_id,
                "mode": MODE_AUTOMATIC, "purpose": PURPOSE_AUTOMATIC,
                "source": "deferred", "reason": str(reason or ""),
                "detail": f"deferred|{detail}" if detail else "deferred"}
        if delivered is not None:
            item["delivered"] = bool(delivered)
        if events:
            item["after"] = str(events[-1].get("name") or "")
        events.append(item)

    async def _terminal(reason_code: str, *, detail: str,
                        event: str = EVENT_PUBLICATION_CANCELLED,
                        delivered: bool = False, delivery: str = "not_sent",
                        job_status: str = JOB_CANCELLED) -> AttemptResult:
        """Терминальный переход: строка журнала ровно одна, файл удалён.

        ``result_ref`` передаётся явно: `TaskJobStore.finish` пишет колонку
        целиком, и без аргумента путь к байтам был бы стёрт из строки.
        """
        facts[STAGE_PUBLISH]["delivery"] = delivery
        facts[STAGE_PUBLISH]["deferred"] = {"job_id": job_id,
                                            "run_id": run_id}
        emit(event, reason=reason_code, detail=detail, delivered=delivered)
        try:
            await store.finish(job_id, status=job_status,
                               reason_code=reason_code,
                               result_ref=result_ref or None,
                               error_code=detail or None)
        except Exception:
            logger.warning("[meme] deferred finish failed | job=%s", job_id,
                           exc_info=True)
        remove_deferred_bytes(result_ref)
        result = AttemptResult(
            chat_id=int(chat_id), stage=STAGE_PUBLISH,
            outcome="published" if delivered else "skipped",
            reason=reason_code, detail=detail, job_id=run_id,
            published=bool(delivered), generated=True,
            counters={STAGE_PUBLISH: 1}, stage_facts=facts,
            manually_triggered=False)
        return await _finish_async(result, ledger=ledger, now_ts=ts,
                                      settings=cfg)

    async def _wait(reason_code: str, detail: str) -> None:
        """Слот/тихие часы: остаёмся `queued`, файл сохранён, строк нет."""
        try:
            await store.requeue(job_id, reason_code=reason_code)
        except Exception:
            logger.warning("[meme] deferred requeue failed | job=%s", job_id,
                           exc_info=True)
        logger.info("[meme] deferred waits | chat=%s | reason=%s | detail=%s",
                    chat_id, reason_code, detail)
        return None

    # (0) Прерванный прогон (watchdog помечает `running` как `interrupted`):
    # доставка не доказана — НЕ переотправляем, честный терминальный факт.
    if status == JOB_INTERRUPTED:
        return await _terminal(REASON_DELIVERY_UNKNOWN, detail="interrupted",
                               event=EVENT_DELIVERY_UNKNOWN,
                               delivery="unknown", job_status=JOB_FAILED)

    # (1) Ретенция истекла — честный срок жизни данных, не тихая потеря.
    if expires_at and ts >= int(expires_at):
        return await _terminal(SKIP_DEFERRED_EXPIRED, detail="expired")

    # (2) Байты обязаны существовать: нет файла — публиковать нечего.
    content = load_deferred_bytes(row)
    if content is None:
        return await _terminal(SKIP_PUBLISH, detail="artifact_missing",
                               job_status=JOB_FAILED)

    # (3)-(5) Содержательные и правовые условия на момент РЕАЛЬНОЙ отправки.
    # MOD-ACL-UX-01 M2 §2.5: тот же порядок осей, что и перед сетевым
    # вызовом ниже (`_final_gate_reason`) — второй копии правил нет.
    block = await _final_gate_reason(
        db, int(chat_id), cfg, chat_enabled=chat_enabled,
        initiative_enabled=initiative_enabled)
    if block:
        return await _terminal(
            block, detail=("chat_gate_disabled" if block ==
                           SKIP_INITIATIVE_DISABLED else "module_disabled"))
    check_rights = rights_check or (
        lambda cid: _default_rights_check(db, int(cid)))
    rights_ok, rights_code, rights_detail = await check_rights(int(chat_id))
    facts[STAGE_PUBLISH]["rights"] = {
        "mode": "roster", "ok": bool(rights_ok),
        "detail": str(rights_detail or "")}
    if not rights_ok:
        return await _terminal(str(rights_code or SKIP_RIGHTS_REVOKED),
                               detail=str(rights_detail or ""))
    # Мем не привязан к intent-записи (свой run_id и собственный снапшот):
    # проверка жизненного цикла намерения для этого механизма N/A. Это факт
    # записывается явно, а не имитируется синтетическим контекстом (B2).
    facts[STAGE_PUBLISH]["intent_lifecycle"] = {
        "status": "n/a", "reason": "meme_has_no_intent_binding"}
    saved_ids = payload.get("msg_ids") or ()
    snapshot = SourceSnapshot(
        chat_id=int(chat_id), run_id=run_id, mode=MODE_AUTOMATIC,
        purpose=PURPOSE_AUTOMATIC, request_ref=str(payload.get("run_id") or ""),
        message_ids=tuple(int(item) for item in saved_ids),
        message_count=int(payload.get("msg_count") or len(saved_ids)),
        first_id=payload.get("first_id"), last_id=payload.get("last_id"),
        digest=str(payload.get("snapshot_digest") or ""), captured_at=ts)
    check_source = source_check or (
        lambda cid, snap: _default_source_check(db, int(cid), snap))
    source_ok, source_code, source_detail = await check_source(
        int(chat_id), snapshot)
    facts[STAGE_PUBLISH]["source_ok"] = bool(source_ok)
    if not source_ok:
        return await _terminal(str(source_code or SKIP_SOURCE_GONE),
                               detail=str(source_detail or ""))

    # (6) Публикационный гейт: тот же существующий шов, что у прямой отправки.
    if publish_gate is None:
        allowed, gate_reason = await _default_publish_gate(db, int(chat_id), ts)
    else:
        allowed, gate_reason = await publish_gate(int(chat_id))
    facts[STAGE_PUBLISH]["gate"] = str(gate_reason or "")
    if not allowed:
        return await _terminal(SKIP_PUBLISH,
                               detail=str(gate_reason or SKIP_PUBLISH))

    # (7) Тихие часы — не терминал: остаёмся в очереди, строк журнала нет.
    if quiet_hours_block(cfg.quiet_hours, stamp, day.timezone_name):
        return await _wait(SKIP_QUIET, "quiet_hours")

    # (8) CAS: только один проход может взять эту строку в работу.
    if not await store.mark_running(job_id):
        return None

    coordinator = publication
    from services import publication_coordination as pubmod
    if coordinator is None:
        coordinator = pubmod.PublicationCoordinator(
            db, store=claim_store if claim_store is not None else
            pubmod.open_store(db, path=(ledger.path if ledger is not None
                                        else None)))
    # Атрибуция брони ДО `acquire` (B4): флаг `recovered_delivery_unknown`
    # описывает ПРЕДЫДУЩЕГО держателя истёкшей `sending`-брони. Своя отправка
    # этого мема не может совпасть с `queued`-строкой: строка переводится в
    # `running` ДО брони, а падение в окне отправки ловит watchdog и мы выше
    # уходим в честный терминал `delivery_unknown` без `acquire`. Значит по
    # смыслу это ЧУЖАЯ бронь (другой механизм упал/завис посреди отправки), и
    # терять из-за неё оплаченную картинку запрещено (§1.2.5).
    before_claim = await coordinator.snapshot(int(chat_id))
    claim = await coordinator.acquire(
        int(chat_id), OUTPUT_KIND, holder_ref=run_id, now=ts, manual=False,
        wait_for_sending=0.0)
    facts[STAGE_PUBLISH]["claim"] = claim.as_dict()
    if claim.recovered_delivery_unknown:
        previous_kind = str((before_claim or {}).get("holder_kind") or "")
        previous_ref = str((before_claim or {}).get("holder_ref") or "")
        own_send = bool(previous_kind == OUTPUT_KIND
                        and previous_ref and previous_ref == str(run_id))
        facts[STAGE_PUBLISH]["delivery_recovered"] = {
            "holder_kind": previous_kind, "holder_ref": previous_ref,
            "own": own_send, "detail": str(claim.detail or "")}
        if own_send:
            # Доказано, что это НАША отправка с неизвестным исходом: повтор
            # дал бы дубль — честный терминал без переотправки.
            return await _terminal(REASON_DELIVERY_UNKNOWN,
                                   detail="recovered_delivery_unknown",
                                   event=EVENT_DELIVERY_UNKNOWN,
                                   delivery="unknown", job_status=JOB_FAILED)
        # Чужая бронь: фиксируем факт (событие + факты) и продолжаем под
        # реально выданной бронью — ровно как прямой путь в этом состоянии.
        emit(EVENT_DELIVERY_UNKNOWN, reason="delivery_unknown",
             detail="foreign_claim")
    if not claim.granted:
        code = (SKIP_PUBLICATION_IN_FLIGHT
                if claim.reason == "publication_in_flight"
                else SKIP_PUBLICATION_CONFLICT)
        return await _wait(code, str(claim.detail or claim.reason or ""))
    emit(EVENT_PUBLICATION_REQUESTED, detail="claim_requested")
    if sender is None:
        await coordinator.release(int(chat_id), claim.claim_id,
                                  published=False, holder_kind=OUTPUT_KIND,
                                  holder_ref=run_id, now=ts)
        # P0IM-S5B-NODISCARD: отправителя в этом процессе нет — это НЕ повод
        # удалять оплаченный артефакт. Строка остаётся `queued` (файл цел,
        # строк журнала нет: ожидание не является попыткой), и первый же
        # проход с привязанным ботом доставит её. Срок ограничен СУЩЕСТВУЮЩЕЙ
        # ретенцией (`expires_at` = собственный кулдаун механизма): после него
        # срабатывает честный терминал `deferred_publication_expired` с фактом
        # «не отправлено» — бесконечного ретрая нет.
        return await _wait(SKIP_PUBLISH, "publisher_not_bound")
    sending = await coordinator.begin_sending(int(chat_id), claim.claim_id,
                                             now=ts, manual=False)
    facts[STAGE_PUBLISH]["sending"] = sending.as_dict()
    if not sending.granted:
        await coordinator.release(int(chat_id), claim.claim_id,
                                  published=False, holder_kind=OUTPUT_KIND,
                                  holder_ref=run_id, now=ts)
        code = (SKIP_PUBLICATION_IN_FLIGHT
                if sending.reason == "publication_in_flight"
                else SKIP_PUBLICATION_EXPIRED)
        return await _wait(code, str(sending.detail or ""))
    # §2.5 M2: ПОСЛЕДНЯЯ проверка чата перед первым side effect — слот
    # отправки мог ждаться, а чат выключили уже после брони.
    block = await _final_gate_reason(
        db, int(chat_id), cfg, chat_enabled=chat_enabled,
        initiative_enabled=initiative_enabled)
    if block:
        await coordinator.release(int(chat_id), claim.claim_id,
                                  published=False, holder_kind=OUTPUT_KIND,
                                  holder_ref=run_id, now=ts)
        # Терминально: байты отложенного результата удаляются, строка закрыта
        # причиной OFF. Так повторное включение не даёт replay/backfill
        # (MAC-S2-115): старый результат не «догоняет» чат задним числом.
        return await _terminal(
            block, detail=("chat_gate_disabled" if block ==
                           SKIP_INITIATIVE_DISABLED else "module_disabled"))
    try:
        message = await sender(int(chat_id), content, "")
    except Exception:
        logger.warning("[meme] deferred publish failed", exc_info=True)
        await coordinator.release(int(chat_id), claim.claim_id,
                                  published=False, holder_kind=OUTPUT_KIND,
                                  holder_ref=run_id, now=ts)
        return await _terminal(REASON_DELIVERY_UNKNOWN, detail="send_failed",
                               event=EVENT_DELIVERY_UNKNOWN,
                               delivery="unknown", job_status=JOB_FAILED)
    tg_message_id = getattr(message, "message_id", None)
    ledger_output_id = await _record_meme_output(
        db, chat_id=int(chat_id), tg_message_id=tg_message_id, sent_at=ts,
        correlation_id=run_id, manual=False)
    facts[STAGE_PUBLISH]["output"] = {"ledger_id": ledger_output_id,
                                      "tg_message_id": tg_message_id}
    await coordinator.release(int(chat_id), claim.claim_id, published=True,
                              holder_kind=OUTPUT_KIND, holder_ref=run_id,
                              now=ts)
    return await _terminal("sent", detail=f"tg:{tg_message_id}",
                           event=EVENT_PUBLICATION_SENT, delivered=True,
                           delivery="sent", job_status=JOB_COMPLETED)


async def _final_gate_reason(db, chat_id: int, cfg: MemeSettings, *,
                            chat_enabled=None, initiative_enabled=None) -> str | None:
    """Код причины, если публиковать мем в этот чат НЕЛЬЗЯ (§2.5 M2).

    Вызывается НЕПОСРЕДСТВЕННО перед сетевым вызовом отправки: генерация
    изображения занимает минуты, и чат могли выключить, пока она шла. Порядок
    осей фиксирован: аварийный/мастер инициативы → чатовый гейт инициативы →
    продуктовый тумблер мемов чата. ``None`` — можно отправлять.

    Проверки дешёвые (кэш настроек) и идемпотентные: повтор не пишет ни
    строк журнала, ни квоты.
    """
    if initiative_enabled is not None:
        try:
            if not initiative_enabled():
                return SKIP_INITIATIVE_DISABLED
        except Exception:
            logger.warning("[meme] initiative gate read failed — allow | "
                           "chat=%s", chat_id, exc_info=True)
    if chat_enabled is not None:
        try:
            if not await chat_enabled(int(chat_id)):
                return SKIP_INITIATIVE_DISABLED
        except Exception:
            logger.warning("[meme] chat gate read failed — allow | chat=%s",
                           chat_id, exc_info=True)
    try:
        module_now = _as_bool(
            await _param(int(chat_id), KEY_ENABLED, cfg.enabled), cfg.enabled)
    except Exception:
        module_now = bool(cfg.enabled)
    if not module_now:
        return SKIP_DISABLED
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


async def consider_chat(db, chat_id: int, *,
                        trace: "RunTrace | None" = None,
                        **kwargs) -> AttemptResult:
    """Одна попытка мема в одном чате: входная точка пайплайна.

    P0IM-D7 / S5-MEME: ОТМЕНА процесса (рестарт сервиса) — тоже терминальный
    исход. ``asyncio.CancelledError`` относится к ``BaseException``, поэтому
    ни один ``except Exception`` пайплайна его не видит: попытка исчезала молча
    (строк журнала нет, пользователю ничего не приходит). Здесь обрыв ловится
    ЯВНО: пишется терминальная строка с реальным этапом остановки и той же
    идентичностью запуска, после чего отмена пробрасывается дальше — это
    остановка процесса, а не повод её глушить.

    ``trace`` передаёт вызывающий слой, когда по месту остановки нужно принять
    решение (обработчик ``/meme``: уведомлять ли пользователя). Остальные
    аргументы — как у одиночного прохода (см. ``_consider_once``).
    """
    run = trace if isinstance(trace, RunTrace) else RunTrace()
    if not run.chat_id:
        run.chat_id = int(chat_id)
    try:
        return await _consider_once(db, chat_id, trace=run, **kwargs)
    except asyncio.CancelledError:
        record_run_interrupted(run)
        raise


async def _consider_once(
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
        request_ref: str = "",
        source_check: Callable[..., Awaitable[tuple]] | None = None,
        rights_check: Callable[..., Awaitable[tuple]] | None = None,
        permission_check: Callable[[], Awaitable[bool]] | None = None,
        manual_priority: dict | None = None,
        trace: RunTrace | None = None,
) -> AttemptResult:
    """Одна попытка мема в одном чате. Дорогое — только после дешёвых гейтов.

    Три этапа в одном проходе: A выжимка (без потолка) → B прикол (при
    ФИКСИРОВАННОМ потолке работает J = max(0, L - T)) → C image prompt.

    ``manual=True`` — диагностический запуск (``/meme``): квота, кулдаун,
    минимум сообщений, случайный триггер, тихие часы, in-flight и гейт
    публикации не применяются; права проверяет вызывающий слой, а готовность
    image-модуля, наличие журнала и разрешимость бюджета остаются гейтами.

    ``claim_store``/``publication`` (INIT-COORD §3): бронь публикации. Без
    явной брони она открывается по тому же файлу, что и журнал квоты; таблицы
    нет → честный ``schema_absent`` (мем не отправляется без координации).

    ``request_ref`` — id инициирующего запроса (сообщение ``/meme`` либо
    инициативный job): попадает в снапшот источника и в события как
    ``request_ref``. ``source_check`` — шов перепроверки исходного материала
    (по умолчанию читает ``smart_messages`` снапшота). ``rights_check`` —
    реальная проверка допустимости чата (по умолчанию ростер кандидатов),
    ``permission_check`` — реальная перепроверка прав автора ручного запроса
    (обработчик `/meme` передаёт сюда тот же RBAC, что и на входе).

    Свежесть переписки НЕ проверяется (§1.2): готовый мем не отменяется из-за
    новых сообщений/watermark. Отмена возможна только по содержательной
    причине — и с точным кодом.
    """
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    ts = int(now_ts if now_ts is not None else stamp.timestamp())
    # ── P0 corrective (§3): родитель попытки mint ДО ПЕРВОГО гейта ──────────
    # Отказ на раннем гейте (`initiative_disabled`, выключенные настройки,
    # image/schema, квота, кулдаун, тихие часы, бронь) — тоже ПОПЫТКА: у неё
    # обязан быть свой ``job_id``. Раньше он создавался после гейтов, `_finish`
    # писал пустой `job_id`, а агрегатор делал ключ `row:{attempt_id}` — одна
    # попытка выглядела двумя строками. Значение зависит только от чата и
    # `stamp`, поэтому вычисляется здесь, до любого `skipped()`.
    day = day_window(chat_id, stamp, tz_name=tz_name, tz_source=tz_source)
    jid = job_id or f"meme:{int(chat_id)}:{day.bucket}:{uuid.uuid4().hex[:12]}"
    # P0IM-D7 / S5-MEME: идентичность попытки уезжает в трассу ДО первого
    # ``await`` — по ней пишется честная терминальная строка, если процесс
    # оборвётся посреди прогона (в т.ч. на загрузке настроек).
    run_trace = trace if isinstance(trace, RunTrace) else None
    if run_trace is not None:
        run_trace.chat_id = int(chat_id)
        run_trace.job_id = jid
        run_trace.stage = STAGE_CONSIDERED
        run_trace.now_ts = int(ts)
        run_trace.manual = bool(manual)
    cfg = settings if settings is not None else await load_settings(chat_id)
    mode = MODE_MANUAL if manual else MODE_AUTOMATIC
    purpose = PURPOSE_MANUAL if manual else PURPOSE_AUTOMATIC
    #: Тот же родитель для ранних ``skipped()`` (см. параметр ``jid`` ниже).
    parent_run_id = jid
    counters = {stage: 0 for stage in STAGES}
    counters[STAGE_CONSIDERED] = 1
    facts: dict[str, dict] = {}
    if run_trace is not None:
        run_trace.settings = cfg
        run_trace.ledger = ledger
        run_trace.counters = counters
        run_trace.facts = facts
    if manual_priority:
        # P0IM-MM-TRACE: «запись приоритета» — ФАКТ попытки, а не только
        # WARNING в логе: неудачная запись маркера ручного `/meme` видна в
        # журнале этого же запуска.
        facts[STAGE_CONSIDERED] = {"priority_marker": dict(manual_priority)}

    async def skipped(reason: str, *, stage: str = STAGE_SKIPPED,
                detail: str = "", limit: MemeBudget | None = None,
                jid: str = "") -> AttemptResult:
        """Ранний отказ ДО генерации; ``job_id`` непустой всегда (§3)."""
        counters[stage] = counters.get(stage, 0) + 1
        result = AttemptResult(
            chat_id=int(chat_id), stage=stage, outcome="skipped",
            reason=reason, detail=detail, job_id=(jid or parent_run_id),
            limit=limit, counters=dict(counters), stage_facts=dict(facts),
            manually_triggered=bool(manual))
        return await _finish_async(result, ledger=ledger, now_ts=ts,
                                      settings=cfg)

    if initiative_enabled is None:
        def initiative_enabled() -> bool:
            from services.initiative_observer import observer_enabled
            return bool(observer_enabled())
    # Тумблеры — часть авто-инициативы, а не диагностики: ручной запуск
    # обязан работать до включения мемов, иначе отладить нечего.
    if not manual:
        if not initiative_enabled():
            return await skipped(SKIP_INITIATIVE_DISABLED)
        if chat_enabled is not None and not await chat_enabled(int(chat_id)):
            return await skipped(SKIP_INITIATIVE_DISABLED)
        if not cfg.enabled:
            return await skipped(SKIP_DISABLED)
        # B1 / arch §8 п.4: в чате уже есть готовый, но ещё не доставленный
        # мем → новый НЕ генерируем (иначе второй платный вызов за тот же
        # результат). Строк журнала не пишем: ожидание — не попытка.
        pending = await deferred_active_row(db, int(chat_id))
        if pending is not None:
            return deferred_wait_result(int(chat_id), pending, ts=ts)

    # Ниже — гейты, которые ручной запуск НЕ обходит: без рабочего image
    # backend мем физически не создать, без журнала некуда писать попытку.
    image = image_status if image_status is not None else \
        await image_dependency(chat_id, health=image_health)
    if not image.get("available"):
        return await skipped(str(image.get("reason") or SKIP_IMAGE_NOT_CONFIGURED))

    if ledger is None or not ledger.table_present():
        return await skipped(SKIP_SCHEMA)

    events: list[dict] = []
    facts["events"] = events

    def emit(name: str, *, reason: str = "", detail: str = "",
             source: str = "", delivered: bool | None = None) -> None:
        """Событие попытки (§1.3): время, run, режим, источник, причина, факт
        доставки и ссылка на предыдущий этап. Текстов сообщений здесь нет."""
        if len(events) >= MAX_EVENTS_PER_ATTEMPT:
            return
        item = {"name": str(name), "at": int(ts), "run_id": str(jid),
                "mode": str(mode), "purpose": str(purpose),
                "source": str(source or ""), "reason": str(reason or ""),
                "detail": str(detail or "")}
        if delivered is not None:
            item["delivered"] = bool(delivered)
        if events:
            item["after"] = str(events[-1].get("name") or "")
        events.append(item)

    async def _cancel(reason_code: str, *, detail: str = "",
                stage: str = STAGE_PUBLISH,
                reason_event: str = EVENT_PUBLICATION_CANCELLED,
                delivered: bool = False) -> AttemptResult:
        """Терминальная отмена ПОСЛЕ генерации: причина честная, картинка не
        выдаётся за отправленную. ``_finish`` пишет и события, и факты этапов.

        Используется только на путях, где изображение уже готово (``budget``,
        ``origin``, ``prompt`` и ``joke`` к этому моменту связаны).
        """
        counters[STAGE_PUBLISH] = counters.get(STAGE_PUBLISH, 0) + 1
        counters[STAGE_SKIPPED] = counters.get(STAGE_SKIPPED, 0) + 1
        facts.setdefault(STAGE_PUBLISH, {})["delivery"] = (
            "sent" if delivered else "not_sent")
        emit(reason_event, reason=str(reason_code), detail=str(detail or ""),
             delivered=delivered)
        result = AttemptResult(
            chat_id=int(chat_id), stage=stage, outcome="skipped",
            reason=reason_code, detail=detail, job_id=jid, prompt=prompt,
            published=False, generated=True, limit=budget,
            prompt_origin=origin, counters=dict(counters),
            stage_facts=dict(facts), joke=joke,
            manually_triggered=bool(manual))
        return await _finish_async(result, ledger=ledger, now_ts=ts,
                                      settings=cfg)

    if not manual:
        view = quota_view(ledger, chat_id=int(chat_id), day=day,
                          limit=cfg.daily_limit)
        if int(cfg.daily_limit) <= 0 or int(view.get("spent") or 0) >= int(
                cfg.daily_limit):
            return await skipped(SKIP_QUOTA)

        last_ts = ledger.last_provider_ts(int(chat_id))
        if cfg.cooldown_seconds and last_ts and \
                ts - last_ts < cfg.cooldown_seconds:
            return await skipped(SKIP_COOLDOWN)

        if quiet_hours_block(cfg.quiet_hours, stamp, day.timezone_name):
            return await skipped(SKIP_QUIET)

    # ── INIT-COORD §3.1: дешёвая ПРОВЕРКА координации публикаций. Стоит после
    # своих кулдаунов/квоты (свои гейты первичны и честны) и ДО чтения окна и
    # LLM-вызовов: если в чате только что публиковался другой механизм или
    # действует приоритет `/meme`, платить за генерацию незачем.
    coordinator = publication
    from services import publication_coordination as pubmod
    if coordinator is None:
        coordinator = pubmod.PublicationCoordinator(
            db, store=claim_store if claim_store is not None else
            pubmod.open_store(db, path=(ledger.path if ledger is not None
                                        else None)))
    # Таблица брони обязательна для мема (arch §3.6): без неё нет «ровно одной
    # публикации», а тихая отправка «на удачу» запрещена. Текстовая инициатива
    # в этом же состоянии деградирует и публикует — мем останавливается.
    if coordinator.store() is not None and not coordinator.available():
        return await skipped(SKIP_SCHEMA, detail="publish_claim_absent", jid=jid)
    precheck = await coordinator.precheck(
        int(chat_id), OUTPUT_KIND, now=ts, manual=bool(manual))
    facts["publication"] = dict(precheck)
    if not precheck.get("ok"):
        reason = str(precheck.get("reason") or SKIP_PUBLICATION_CONFLICT)
        code = (SKIP_PUBLICATION_IN_FLIGHT
                if reason == "publication_in_flight"
                else SKIP_PUBLICATION_CONFLICT)
        return await skipped(code, detail=str(precheck.get("detail") or ""), jid=jid)

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
        return await skipped(SKIP_SUMMARY, detail="chat_mix")
    if not rows:
        # Пустое окно — не «мало сообщений»: генерировать не из чего даже
        # в ручном режиме. Отдельный detail, чтобы причина была видна.
        return await skipped(SKIP_ACTIVITY, detail="window_empty", jid=jid)
    if not manual and len(rows) < cfg.min_messages:
        return await skipped(SKIP_ACTIVITY, jid=jid)

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
            return await skipped(draw.reason,
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
        return await skipped(SKIP_TEMPLATE_EMPTY, stage=STAGE_FAILED,
                       detail="template_missing", jid=jid)
    if model_chars is None and prompt_override is None:
        model_chars = await model_prompt_chars()
    budget = resolve_meme_budget(
        model_chars=model_chars, admin=cfg.length_admin,
        explicit=cfg.length_override, template=template)
    if budget.known and budget.joke_budget <= 0:
        # Фиксированный потолок и T уже съел его целиком: J = 0. Честный
        # пропуск ДО LLM-вызова (испорченную шутку не генерируем).
        # В режиме АВТО этого условия нет: предела просто не задано.
        return await skipped(SKIP_NO_JOKE_BUDGET, limit=budget, jid=jid)

    # Guard «генерация уже идёт» — ДО платной выжимки: иначе чужая свежая
    # бронь съедала бы LLM-вызов впустую (порядок проверок — до дорогих).
    if not manual and ledger.fresh_inflight(int(chat_id), ts) and not job_id:
        return await skipped(SKIP_IN_FLIGHT, limit=budget, jid=jid)

    summary_prompt = await effective_meme_prompt(
        chat_id, SUMMARY_PROMPT_BLOCK_ID, factory=MEME_SUMMARY_SYSTEM_PROMPT)
    summary_system = str(summary_prompt.get("text") or MEME_SUMMARY_SYSTEM_PROMPT)
    # ── СНАПШОТ ИСТОЧНИКА (§1.2.1): входной материал ИМЕННО этого мема.
    # Чат при этом не обязан стоять на месте: снапшот фиксируется один раз и
    # больше не сравнивается ни с watermark, ни с latest_message_id.
    snapshot = build_source_snapshot(
        chat_id=int(chat_id), rows=rows, run_id=jid, mode=mode,
        purpose=purpose, request_ref=request_ref, now_ts=ts)
    pub_facts: dict = facts.setdefault("publication", {})
    if not isinstance(pub_facts, dict):
        pub_facts = {}
        facts["publication"] = pub_facts
    pub_facts["source"] = snapshot.as_dict()
    emit(EVENT_SOURCE_SNAPSHOT, source=str(summary_prompt.get("source") or ""),
         detail=f"messages:{snapshot.message_count}")

    # ── этап A — выжимка: БЕЗ потолка длины (ни цели, ни обрезки) ───────────
    if run_trace is not None:
        run_trace.stage = STAGE_SUMMARY
    try:
        if summarizer is None:
            _summary_speech = SpeechProjection(run_id=str(jid))
            summary = await _default_summarize(
                llm, rows, summary_system, chat_id=int(chat_id),
                model=cfg.summarizer_model, projection=_summary_speech,
                correlation_id=f"{jid}#meme_summary")
            # Обратная карта прогона (§4.2 п.5): выжимка становится словами
            # мема/картинкой, поэтому пары «метка → tg:/msg:» остаются в
            # защищённой трассе (ID/счётчики, без текстов).
            emit_speech_projection_event(_summary_speech, chat_id=int(chat_id),
                                         run_id=_summary_speech.run_id)
        else:
            summary = await summarizer(int(chat_id), rows, summary_system)
    except Exception as exc:
        logger.warning("[meme] summary failed | chat=%s | error=%s",
                       chat_id, type(exc).__name__)
        return await skipped(SKIP_SUMMARY, stage=STAGE_FAILED,
                       detail=f"exception:{type(exc).__name__}", limit=budget,
                       jid=jid)
    summary = str(summary or "").strip()
    if not summary:
        return await skipped(SKIP_SUMMARY, stage=STAGE_FAILED, detail="empty_summary",
                       limit=budget, jid=jid)
    counters[STAGE_SUMMARY] = 1
    facts[STAGE_SUMMARY] = {
        "chars": len(summary),
        "source": summary_prompt.get("source"),
        # §P0IM-PB-LLM: идентичность шага (провайдер/модель/слот) и
        # источник/редакция/sha12 промпта — без текста сообщений и ответа.
        "llm": _llm_identity(llm, hook=summarizer is not None),
        "prompt": _prompt_identity(summary_prompt, summary_system),
    }
    emit(EVENT_DIGEST_READY, source=str(summary_prompt.get("source") or ""),
         detail=f"chars:{len(summary)}")

    # ── этап B — прикол: единственное место, где работает потолок длины ─────
    joke_prompt = await effective_meme_prompt(
        chat_id, JOKE_PROMPT_BLOCK_ID, factory=MEME_JOKE_PROMPT)
    instruction = joke_instruction(
        str(joke_prompt.get("text") or MEME_JOKE_PROMPT),
        budget.joke_budget if budget.known else None)
    joke_speech: dict = {}
    if run_trace is not None:
        run_trace.stage = STAGE_JOKE
    try:
        if joke_generator is None:
            raw_joke, joke_speech = await _default_joke(
                llm, summary, instruction=instruction, chat_id=int(chat_id),
                base_source=_speech_base_source(
                    str(joke_prompt.get("source") or "")), job_id=jid,
                correlation_id=f"{jid}#meme_joke")
        else:
            raw_joke = await joke_generator(int(chat_id), summary, instruction)
    except Exception as exc:
        logger.warning("[meme] joke failed | chat=%s | error=%s",
                       chat_id, type(exc).__name__)
        return await skipped(SKIP_JOKE_FAILED, stage=STAGE_FAILED,
                       detail=f"exception:{type(exc).__name__}", limit=budget,
                       jid=jid)
    joke, trimmed = trim_joke(str(raw_joke or ""),
                              budget.joke_budget if budget.known else 0)
    if not joke:
        return await skipped(SKIP_JOKE_EMPTY, stage=STAGE_FAILED, detail="empty_joke",
                       limit=budget, jid=jid)
    counters[STAGE_JOKE] = 1
    facts[STAGE_JOKE] = {
        # В режиме АВТО числового предела нет: None, а не «0 символов».
        "limit": int(budget.joke_budget) if budget.known else None,
        "template_chars": int(budget.template_chars),
        "ceiling": budget.ceiling,
        "mode": budget.mode,
        "chars": len(joke),
        "trimmed": bool(trimmed),
        "source": str(joke_prompt.get("source") or ""),
        "placeholder": budget.placeholder,
        # §P0IM-PB-LLM: короткая идентичность вызова и промпта шага.
        "llm": _llm_identity(llm, hook=joke_generator is not None),
        "prompt": _prompt_identity(joke_prompt, instruction),
    }
    if joke_speech:
        # MEME-JOKE-SPEECH: фактические ревизии Core/Expression/юмора и
        # манифест сборки — аддитивно рядом с прежними ключами этапа.
        facts[STAGE_JOKE]["speech"] = joke_speech
    emit(EVENT_JOKE_READY, source=str(joke_prompt.get("source") or ""),
         detail=f"chars:{len(joke)}")

    # ── этап C — итоговый prompt из шаблона и ПРИКОЛА (не из выжимки) ───────
    prompt = render_image_prompt(template, joke)
    facts[STAGE_IMAGE] = {
        "chars": len(prompt),
        "template_chars": int(budget.template_chars),
        "ceiling": budget.ceiling,
        "template_revision": str(image_prompt.get("factory_revision") or ""),
        "template_source": str(image_prompt.get("source") or ""),
        "joke_chars": len(joke),
        # §P0IM-PB-LLM: sha12 готового промпта без его текста.
        "prompt_sha12": _text_sha12(prompt),
    }
    if not image_prompt_fits(prompt, budget):
        # Инвариант T + len(прикол) <= L нарушен: провайдеру испорченный
        # prompt НЕ уходит (это конфигурационная ошибка, а не «устаревание»).
        return await skipped(SKIP_NO_JOKE_BUDGET, stage=STAGE_FAILED,
                       detail=f"prompt_over_ceiling:{len(prompt)}>"
                              f"{budget.ceiling}",
                       limit=budget, jid=jid)

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
                return await skipped(SKIP_SLOT_RELEASED, detail="job_released",
                               limit=budget, jid=jid)
            if reserved.status in ("provider_called", "provider_failed"):
                # Тот же job уже дошёл до провайдера: второй слот не берём и
                # второй платный вызов не делаем.
                return await skipped(SKIP_QUOTA, detail="job_already_counted",
                               limit=budget, jid=jid)
            return await skipped(SKIP_QUOTA,
                           detail=f"job_{reserved.status or 'denied'}",
                           limit=budget, jid=jid)
        if not reserved.ok:
            return await skipped(reserved.reason, limit=budget, jid=jid)

    called = False
    provider_result = None
    if run_trace is not None:
        run_trace.stage = STAGE_IMAGE
    try:
        if image_provider is None:
            provider_result = await _default_image(prompt, int(chat_id), jid)
        else:
            provider_result = await image_provider(prompt, int(chat_id), jid)
        called = bool(getattr(provider_result, "called", True))
        ok = bool(getattr(provider_result, "ok", False))
        reason = str(getattr(provider_result, "reason", "") or "")
        content = getattr(provider_result, "content", None)
        if ok and content is None:
            # «Провайдер ответил успехом», но изображения нет: публиковать
            # нечего. Честная техническая причина, а не «устаревание».
            ok = False
            reason = reason or "empty_content"
    except Exception:
        logger.warning("[meme] image provider failed", exc_info=True)
        called = True
        ok = False
        reason = "exception"
        content = None
    try:
        image_bytes = len(content) if content is not None else 0
    except Exception:
        image_bytes = 0
    image_filename = str(getattr(provider_result, "filename", "") or "")
    image_format = _image_format(image_filename)
    # §P0IM-PB-LLM: статус Image API, формат (из имени файла, если записано) и
    # наличие байтов — короткие факты шага, без промпта/байтов изображения.
    facts[STAGE_IMAGE]["api"] = {
        "called": bool(called),
        "ok": bool(ok),
        "status": ("ok" if ok else (reason or "failed")),
        "bytes": int(image_bytes),
        "bytes_present": bool(image_bytes),
        "format": image_format,
        "format_source": ("filename" if image_format else ""),
        "filename_present": bool(image_filename),
    }
    if not called:
        if not manual:
            ledger.mark(jid, "released", reason or "not_called")
        return await skipped(SKIP_IMAGE_FAILED, stage=STAGE_FAILED,
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
        return await _finish_async(result, ledger=ledger, now_ts=ts,
                                      settings=cfg)
    if not manual:
        ledger.mark(jid, "provider_called", "")
    counters[STAGE_IMAGE] = 1
    if run_trace is not None:
        run_trace.stage = STAGE_PUBLISH
    emit(EVENT_IMAGE_READY, source=str(origin),
         detail=f"prompt:{len(prompt)}|bytes:{image_bytes}")

    # ── СОДЕРЖАТЕЛЬНЫЕ проверки перед броней (§1.2.4). Свежесть переписки
    # здесь НЕ проверяется: ни watermark, ни latest_message_id не сравниваются.
    # Отмена — только по реальному терминальному условию, со своим кодом.
    if not manual:
        module_now = _as_bool(
            await _param(int(chat_id), KEY_ENABLED, cfg.enabled), cfg.enabled)
        if not module_now:
            return await _cancel(SKIP_DISABLED,
                           detail="module_disabled_during_generation")
        if not initiative_enabled():
            return await _cancel(SKIP_INITIATIVE_DISABLED,
                           detail="initiative_disabled_during_generation")
        if chat_enabled is not None and not await chat_enabled(int(chat_id)):
            return await _cancel(SKIP_INITIATIVE_DISABLED,
                           detail="chat_gate_disabled_during_generation")
    # B2 (§1.2.4/§3.3): права/допустимость чата перепроверяются на РЕАЛЬНОМ
    # пути — ростер кандидатов для авто-мема и тот же RBAC обработчика для
    # ручного `/meme`. Мок publish-гейта доказательством не считается.
    if manual:
        if permission_check is None:
            pub_facts["rights"] = {"mode": "permission_hook", "ok": True,
                                   "detail": "no_permission_hook"}
        else:
            try:
                permitted = bool(await permission_check())
            except Exception:
                permitted = False
            pub_facts["rights"] = {"mode": "permission_hook",
                                   "ok": permitted,
                                   "detail": "" if permitted
                                   else "permission_denied"}
            if not permitted:
                return await _cancel(SKIP_RIGHTS_REVOKED,
                               detail="permission_denied")
    else:
        # Ростер доказывает права только если окно мема прочитано из ЭТОЙ БД:
        # при диагностическом шве `messages`/`message_reader` чата в ней может
        # не быть, и «нет в ростере» ничего не доказывает (как и у проверки
        # исходного материала). Отсутствие данных не отменяет готовый мем.
        roster_applicable = message_reader is None and messages is None
        if not roster_applicable:
            pub_facts["rights"] = {"mode": "roster", "ok": True,
                                   "detail": "roster_not_applicable"}
        else:
            check_rights = rights_check or (
                lambda cid: _default_rights_check(db, int(cid)))
            rights_ok, rights_code, rights_detail = await check_rights(
                int(chat_id))
            pub_facts["rights"] = {"mode": "roster", "ok": bool(rights_ok),
                                   "detail": str(rights_detail or "")}
            if not rights_ok:
                return await _cancel(str(rights_code or SKIP_RIGHTS_REVOKED),
                               detail=str(rights_detail or ""))
    # Жизненный цикл intent: мем не привязан к intent-записи (свой run_id и
    # собственный снапшот источника) — фиксируем N/A с причиной, а не
    # имитируем проверку синтетической строкой контекста.
    pub_facts["intent_lifecycle"] = {
        "status": "n/a", "reason": "meme_has_no_intent_binding"}
    check_source = source_check
    if check_source is None:
        # Окно, прочитанное НЕ из `smart_messages` (диагностический шов
        # `messages`/`message_reader`), в этой БД не проверить: утрату
        # материала не выдумываем. Штатный авто-путь читает окно из БД.
        from_db = message_reader is None and messages is None
        if from_db:
            async def check_source(cid, snap):
                return await _default_source_check(db, int(cid), snap)
        else:
            async def check_source(cid, snap):
                return True, "", ""
    source_ok, source_code, source_detail = await check_source(
        int(chat_id), snapshot)
    pub_facts["source_ok"] = bool(source_ok)
    if not source_ok:
        return await _cancel(str(source_code or SKIP_SOURCE_GONE),
                       detail=str(source_detail or ""))

    # ── INIT-COORD §3.3/§3.5: атомарная бронь публикации ПЕРЕД гейтом и
    # отправкой. Проигравший не отправляет уже сгенерированную картинку ни
    # сейчас, ни позже; собственный кулдаун/квота при этом не сбрасываются.
    # Ручной запрос приоритетен: он ДОЖИДАЕТСЯ освобождения чужой активной
    # отправки существующим durable-механизмом (release-event), а не теряет
    # уже готовую картинку.
    claim = await coordinator.acquire(
        int(chat_id), OUTPUT_KIND, holder_ref=jid, now=ts,
        manual=bool(manual),
        wait_for_sending=(float(pubmod.MANUAL_IN_FLIGHT_WAIT_SECONDS)
                          if manual else 0.0))
    pub_facts["manual"] = bool(manual)
    pub_facts["claim"] = claim.as_dict()
    if claim.recovered_delivery_unknown:
        # Существующий протокол: прошлая бронь осталась в `sending`, доставка
        # не доказана и не опровергнута — так и записываем, не выдавая за 0.
        pub_facts["delivery"] = "unknown"
        emit(EVENT_DELIVERY_UNKNOWN, reason="delivery_unknown",
             detail=str(claim.detail or "delivery_unknown"))
    if not claim.granted:
        counters[STAGE_PUBLISH] = 1
        counters[STAGE_SKIPPED] = counters.get(STAGE_SKIPPED, 0) + 1
        code = (SKIP_PUBLICATION_IN_FLIGHT
                if claim.reason == "publication_in_flight"
                else SKIP_PUBLICATION_CONFLICT)
        facts.setdefault(STAGE_PUBLISH, {})["delivery"] = "not_sent"
        # B1 (§1.2.5): готовый авто-мем НЕ выбрасывается — байты уходят в
        # durable-очередь и доставляются существующим тиком при свободном слоте.
        # Ручной `/meme` не откладывает: он ждёт слот сам (B3).
        if not manual:
            deferred = await defer_generated_meme(
                db, chat_id=int(chat_id), content=content, snapshot=snapshot,
                run_id=jid, reason=code,
                detail=str(claim.detail or claim.reason or ""), cfg=cfg,
                prompt_origin=origin, now_ts=ts)
            if deferred:
                pub_facts["deferred"] = deferred
                facts.setdefault(STAGE_PUBLISH, {})["deferred"] = deferred
        emit(EVENT_PUBLICATION_DEFERRED, reason=code,
             detail=str(claim.detail or claim.reason or ""), delivered=False)
        result = AttemptResult(
            chat_id=int(chat_id), stage=STAGE_PUBLISH, outcome="skipped",
            reason=code, detail=str(claim.detail or claim.reason or ""),
            job_id=jid, prompt=prompt, published=False, generated=True,
            limit=budget, prompt_origin=origin, counters=dict(counters),
            stage_facts=dict(facts), joke=joke,
            manually_triggered=bool(manual))
        return await _finish_async(result, ledger=ledger, now_ts=ts,
                                      settings=cfg)

    emit(EVENT_PUBLICATION_REQUESTED, source=str(origin),
         detail=f"claim:{str(claim.claim_id or '')[:12]}")

    async def _drop_claim(reason_code: str, *, detail: str = "",
                          stage: str = STAGE_PUBLISH,
                          reason_event: str = EVENT_PUBLICATION_CANCELLED,
                          delivered: bool = False) -> AttemptResult:
        await coordinator.release(int(chat_id), claim.claim_id, published=False,
                                  holder_kind=OUTPUT_KIND, holder_ref=jid,
                                  now=ts)
        return await _cancel(reason_code, detail=detail, stage=stage,
                       reason_event=reason_event, delivered=delivered)

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
        if not allowed:
            blocked = await _drop_claim(SKIP_PUBLISH,
                                        detail=str(gate_reason or SKIP_PUBLISH))
        else:
            # P0IM-S5B-NODISCARD (§1.2.5 «не отменять готовые изображения»):
            # изображение УЖЕ оплачено и получено, а отправителя в этом
            # процессе нет (событийный тик без привязанного бота — штатный
            # случай, а не поломка конфигурации). Раньше байты удалялись, а
            # слот квоты оставался израсходованным: пользователь не получал
            # ничего и не видел причины. Теперь результат уходит в
            # СУЩЕСТВУЮЩУЮ durable-очередь B1 (`task_jobs` + файл), и штатный
            # проход с привязанным ботом доставит его при первом свободном
            # слоте. Новых очередей/таблиц/планировщиков нет.
            deferred = None
            if not manual:
                deferred = await defer_generated_meme(
                    db, chat_id=int(chat_id), content=content,
                    snapshot=snapshot, run_id=jid, reason=SKIP_PUBLISH,
                    detail="publisher_not_bound", cfg=cfg,
                    prompt_origin=origin, now_ts=ts)
            pub_facts["artifact"] = {
                "reason": "publisher_not_bound",
                "bytes": int(image_bytes),
                # `preserved=false` — честный факт: durable-путь недоступен,
                # байты сохранить негде. Такой исход виден, а не «как будто
                # всё сохранили».
                "preserved": bool(deferred),
                "deferred_job_id": str((deferred or {}).get("job_id") or ""),
            }
            # Доставки в этом проходе не было — это ФАКТ попытки, а не вывод
            # читателя: ось доставки обязана показать «не доставлено».
            pub_facts["delivery"] = "not_sent"
            if deferred:
                pub_facts["deferred"] = deferred
                facts.setdefault(STAGE_PUBLISH, {})["deferred"] = deferred
                logger.info("[meme] paid image deferred | chat=%s | "
                            "reason=publisher_not_bound | job=%s",
                            chat_id, (deferred or {}).get("job_id"))
            else:
                logger.warning("[meme] paid image not deliverable | chat=%s | "
                               "reason=publisher_not_bound | preserved=false",
                               chat_id)
            blocked = await _drop_claim(
                SKIP_PUBLISH, detail="publisher_not_bound",
                reason_event=(EVENT_PUBLICATION_DEFERRED if deferred
                              else EVENT_PUBLICATION_FAILED))
        blocked.outcome = "blocked"
        return blocked
    # ── §2.5 M2: финальная проверка ЧАТА перед первым side effect. Картинка
    # уже сгенерирована (минуты), поэтому OFF, выставленный в полёте, обязан
    # отменить публикацию: результат — ровно один терминальный исход с
    # причиной, без второй доставки. Ручной `/meme` — диагностика и не
    # гейтится пользовательским тумблером (прежнее поведение).
    # В отложенную очередь результат НЕ кладётся: это «догрузка» после
    # включения, то есть неконтролируемый replay/backfill (MAC-S2-115).
    if not manual:
        block = await _final_gate_reason(
            db, int(chat_id), cfg, chat_enabled=chat_enabled,
            initiative_enabled=initiative_enabled)
        if block:
            facts.setdefault(STAGE_PUBLISH, {})["capability"] = str(block)
            dropped = await _drop_claim(
                block, detail="chat_gate_disabled"
                if block == SKIP_INITIATIVE_DISABLED else "module_disabled")
            dropped.outcome = "blocked"
            return dropped
    # ── `claimed → sending` — единственное разрешение звать sender ─────────
    sending = await coordinator.begin_sending(int(chat_id), claim.claim_id,
                                              now=ts, manual=bool(manual))
    pub_facts["sending"] = sending.as_dict()
    if not sending.granted:
        code = (SKIP_PUBLICATION_IN_FLIGHT
                if sending.reason == "publication_in_flight"
                else SKIP_PUBLICATION_EXPIRED)
        event = (EVENT_PUBLICATION_DEFERRED
                 if sending.reason == "publication_in_flight"
                 else EVENT_PUBLICATION_CANCELLED)
        return await _drop_claim(code, detail=str(sending.detail or ""),
                                 reason_event=event)
    try:
        # Доставка не меняется: sender получает ТОЛЬКО изображение; prompt и
        # прикол остаются внутренними (никогда не caption и не сообщение).
        message = await sender(int(chat_id), content, prompt)
        if run_trace is not None:
            # Отправка подтверждена транспортом: обрыв ПОСЛЕ этого — уже
            # публикация, а не провал (см. `record_run_interrupted`).
            run_trace.delivered = True
    except Exception:
        logger.warning("[meme] publish failed", exc_info=True)
        counters[STAGE_FAILED] = 1
        await coordinator.release(int(chat_id), claim.claim_id,
                                  published=False, holder_kind=OUTPUT_KIND,
                                  holder_ref=jid, now=ts)
        # Отправка бросила исключение: доставка НЕ доказана и НЕ опровергнута.
        # Врать «не отправлено» нельзя — используется существующий протокол
        # неизвестного статуса, дальше решает ledger/бронь.
        pub_facts["delivery"] = "unknown"
        facts.setdefault(STAGE_PUBLISH, {})["delivery"] = "unknown"
        emit(EVENT_DELIVERY_UNKNOWN, reason="delivery_unknown",
             detail="send_failed")
        result = AttemptResult(
            chat_id=int(chat_id), stage=STAGE_PUBLISH, outcome="blocked",
            reason=SKIP_PUBLISH, detail="send_failed", job_id=jid,
            prompt=prompt, published=False, generated=True, limit=budget,
            prompt_origin=origin, counters=dict(counters),
            stage_facts=dict(facts), joke=joke,
            manually_triggered=bool(manual))
        return await _finish_async(result, ledger=ledger, now_ts=ts,
                                      settings=cfg)
    counters[STAGE_PUBLISH] = 1
    tg_message_id = getattr(message, "message_id", None)
    ledger_output_id = await _record_meme_output(
        db, chat_id=int(chat_id), tg_message_id=tg_message_id, sent_at=ts,
        correlation_id=jid, manual=bool(manual))
    pub_facts["output"] = {"ledger_id": ledger_output_id,
                           "tg_message_id": tg_message_id}
    pub_facts["delivery"] = "sent"
    facts.setdefault(STAGE_PUBLISH, {})["delivery"] = "sent"
    await coordinator.release(int(chat_id), claim.claim_id, published=True,
                              holder_kind=OUTPUT_KIND, holder_ref=jid, now=ts)
    emit(EVENT_PUBLICATION_SENT, reason="sent",
         detail=f"tg:{tg_message_id}", delivered=True)
    result = AttemptResult(
        chat_id=int(chat_id), stage=STAGE_PUBLISH, outcome="published",
        reason="sent", job_id=jid, prompt=prompt, published=True,
        generated=True, limit=budget, prompt_origin=origin,
        counters=dict(counters), stage_facts=dict(facts), joke=joke,
        manually_triggered=bool(manual))
    return await _finish_async(result, ledger=ledger, now_ts=ts,
                              settings=cfg)


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
                             model: str = "",
                             projection=None,
                             correlation_id: str = "") -> str:
    """Этап A: лёгкий контур выжимки — ОДИН вызов существующего LLM-клиента.

    Тяжёлый summary-pipeline (planner → writer → reviewer) не используется.
    Потолка длины здесь НЕТ (MEME-PIPELINE-REFactor-01 §1): в payload не
    уходит ``target_chars``, постфактум-обрезки тоже нет. Нет клиента/вызова —
    честный ``RuntimeError``, не тихая подстановка чужого текста.

    EVOL v5 (§4.1 P7, §4.2 п.2/п.3): поле ``id`` сообщения — служебный ключ,
    а выжимка становится словами мема/прикола (в т.ч. изображением), поэтому
    в речевом режиме в нём стоит МЕТКА прогона (``M1``), а не внутренний id.
    Различимость сообщений сохраняется (порядок и метка), номер строки БД —
    нет. ``projection``/рубильник OFF → прежний payload байт-в-байт."""
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
    speech = projection is not None and speech_projection_enabled()
    payload = {
        "messages": [
            {
                "id": (
                    projection.message_label(resolve_item_id(
                        tg_message_id=row.get("tg_message_id"),
                        message_id=row.get("id")))
                    if speech else row.get("id")),
                "text": str(row.get("text") or "")[:500],
            }
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
                 correlation_id=str(correlation_id or
                                    uuid.uuid4().hex[:16])),
        timeout=SUMMARY_TIMEOUT_SECONDS)
    return str(raw or "").strip()


@dataclass(frozen=True)
class JokeAdvice:
    """Совет юмора для композера: приём Humor Craft (нулевой LLM-вызов).

    Композер читает ``comic_strategy`` ДО подмены PlanRef, поэтому текста
    L1-плана в payload нет (``plan_skip=no_l1_plan_in_genre``), а приём
    доезжает до слоя ``humor_craft``.
    """

    comic_strategy: str = ""
    extent: str = ""
    structure: str = ""
    tone: str = ""


def _text_sha12(text: str) -> str:
    """12-hex sha256 — та же ревизия, что у композера/реестра промптов."""
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def _llm_identity(llm, *, hook: bool = False) -> dict:
    """Короткая идентичность ФАКТИЧЕСКОГО LLM-вызова для ``detail`` этапа.

    P0IM-PB-LLM: в журнал попадают только provider/model и честная причина
    отсутствия слота — без текста сообщений, выжимки, прикола и промптов
    (R17 и размер durable-записи). Значения берутся у того же клиента, что
    реально делал вызов (``llm._chat_model``/``llm._provider_label`` — уже
    существующий шов, которым пользуется этап A), а не из текущих настроек.
    Слота у мем-пайплайна нет: ``slot=None`` + ``slot_reason="slot_not_used"``.
    ``hook=True`` — шаг исполнял вызывающий шов (тест/диагностика), а не этот
    клиент: модель не приписывается, причина названа честно.
    """
    if hook:
        return {"provider": None, "model": None, "slot": None,
                "slot_reason": "slot_not_used",
                "reason": "custom_step_hook"}
    model = ""
    provider = ""
    try:
        model = str(getattr(llm, "_chat_model", "") or "")
    except Exception:
        model = ""
    try:
        label = getattr(llm, "_provider_label", None)
        if callable(label):
            provider = str(label(model) or "")
    except Exception:
        provider = ""
    return {"provider": provider or None, "model": model or None,
            "slot": None, "slot_reason": "slot_not_used"}


def _prompt_identity(prompt: dict, text: str) -> dict:
    """Источник/редакция/sha12 промпта шага — без самого текста.

    ``sha12`` считается по тому тексту, который реально передан шагу
    (system выжимки / инструкция прикола); полный собранный system этапа B
    остаётся в существующем ``facts.joke.speech.system_sha12``.
    """
    data = prompt if isinstance(prompt, dict) else {}
    revision = data.get("revision")
    return {"block": str(data.get("block_id") or ""),
            "source": str(data.get("source") or ""),
            "revision": (None if revision in (None, "") else revision),
            "sha12": _text_sha12(text)}


def _image_format(filename) -> str:
    """Формат изображения из имени файла провайдера (если оно записано)."""
    text = str(filename or "").strip().lower()
    _base, dot, ext = text.rpartition(".")
    if not dot or not ext or len(ext) > 5 or not ext.isalnum():
        return ""
    return ext


def _speech_base_source(layer: str) -> str:
    """Провенанс задания для композера (закрытый набор ``SOURCES``).

    Чат/глобальный слой различимы; заводская редакция, реестр и явный
    override — ``default`` (новых значений не вводим).
    """
    return "chat" if str(layer or "") == "chat" else (
        "global" if str(layer or "") == "global" else "default")


async def joke_technique(chat_id: int | None, job_id: str, *, gates) -> str:
    """Приём Humor Craft для этапа B: детерминированная ротация по ``job_id``.

    Приём НЕ выбирает LLM (доп. вызовов нет) и НЕ один захардкоженный: список
    техник берётся из документа владельца ``humor.craft``
    (``mca_humor_craft.resolve_config``) — выключенные техники не выбираются
    никогда, включённые участвуют в ротации ``sha256(job_id) % len(enabled)``.
    Пусто → слоя нет; причина остаётся в манифесте (``humor_disabled``).
    """
    if not getattr(gates, "humor_craft_enabled", False):
        return ""
    try:
        from services import mca_humor_craft as craft
        cfg = await craft.resolve_config(chat_id)
    except Exception:
        logger.warning("[meme] humor craft config unreadable — слой пропущен",
                       exc_info=True)
        return ""
    if not cfg.enabled:
        return ""
    enabled = [name for name in craft.TECHNIQUES if cfg.technique_enabled(name)]
    if not enabled:
        return ""
    digest = hashlib.sha256(str(job_id or "").encode("utf-8")).hexdigest()
    return enabled[int(digest, 16) % len(enabled)]


def _speech_facts(system: str, manifest, technique: str) -> dict:
    """Диагностика речевой сборки этапа B (аддитивно, в ``detail`` журнала).

    Без ``versions["humor"]``: ключа в композере нет, а его добавление сдвинуло
    бы ``manifest_id`` всех Writer'ов. Ревизия приёма берётся из трассы слоя
    ``humor_craft``; текст прикола и сырые тексты слоёв сюда не попадают.
    """
    if manifest is None:
        return {"composer": "failed", "system_sha12": _text_sha12(system)}
    from services import prompt_composer as pc
    versions = dict(manifest.versions or {})
    traces = tuple(manifest.layers or ())
    humor = next((t for t in traces if t.layer == pc.LAYER_HUMOR_CRAFT), None)
    if humor is not None and humor.rendered:
        humor_status = "rendered"
    else:
        humor_status = "skip:" + str(
            (humor.skip_reason if humor is not None else "") or
            "humor_no_strategy")
    skipped: dict[str, str] = {}
    for trace in traces:
        if trace.rendered or not trace.skip_reason:
            continue
        previous = skipped.get(trace.layer)
        skipped[trace.layer] = (
            previous + "|" + trace.skip_reason
            if previous and previous != trace.skip_reason
            else (previous or trace.skip_reason))
    return {
        "composer": "on",
        "system_sha12": pc.sha12(system),
        "manifest": str(manifest.manifest_id or ""),
        "core": str(versions.get("core") or ""),
        "core_detail": str(versions.get("core_detail") or ""),
        "identity": str(versions.get("identity") or ""),
        "expression": str(versions.get("expression") or ""),
        "style_policy": str(versions.get("style_policy") or ""),
        "humor": (str(humor.revision or "") if humor is not None else ""),
        "technique": str(technique or ""),
        "humor_status": humor_status,
        "layers": [{"layer": t.layer, "block": t.block_id,
                    "revision": t.revision, "chars": int(t.chars or 0),
                    "rendered": bool(t.rendered),
                    "skip": t.skip_reason} for t in traces],
        "skipped": skipped,
        "off_axes": sorted(name for name, value in
                           (manifest.flags or {}).items() if not value),
    }


async def _joke_system_prompt(chat_id: int | None, *, instruction: str,
                              base_source: str, summary: str,
                              job_id: str) -> tuple[str, dict]:
    """System этапа B через ЕДИНЫЙ композер речи (ноль LLM-вызовов).

    Задание (редактируемый промпт прикола + J-директива) едет слоем
    ``channel_contract`` первым; речевые слои владельца дописываются после него
    и заданием не вытесняются (аддитивного бюджета инструкций нет). Отдельного
    композера/второй копии Core/нового агента здесь нет.

    Композер fail-open: сбой сборки → база канала (payload этапа B
    байт-в-байт сегодняшний) и ``composer="failed"``; прикол выжимкой не
    подменяется.
    """
    base = str(instruction or "")
    try:
        from services import prompt_composer as pc
    except Exception:                      # pragma: no cover — защитная ветка
        logger.warning("[meme] speech composer unavailable — база канала",
                       exc_info=True)
        return base, {"composer": "failed", "system_sha12": _text_sha12(base)}
    chat_key = int(chat_id) if chat_id is not None else 0
    technique = ""
    identity_text = ""
    identity_skipped = "identity_absent"
    try:
        gates = await pc.resolve_gates(chat_key)
        technique = await joke_technique(chat_key, job_id, gates=gates)
        if getattr(gates, "persona_enabled", True):
            try:
                from services import bot_persona
                identity_text, _ctx = await bot_persona.resolve_character_block(
                    chat_key)
            except Exception:
                logger.warning("[meme] persona block unavailable — слой "
                               "пропущен", exc_info=True)
                identity_text = ""
            identity_skipped = "" if str(identity_text or "").strip() \
                else "identity_absent"
        else:
            identity_skipped = "persona_disabled"
        system, manifest = await pc.compose_speech_system(
            chat_id=chat_key, writer=JOKE_SPEECH_WRITER,
            run_id=(str(job_id) or None), channel="plain", html_safe=False,
            base_prompt=base, base_source=base_source,
            include_mode_block=False, profile=pc.PROFILE_SPEECH_PLAIN,
            gates=gates, include_speech_base=True, extent_block="",
            plan_skip=JOKE_PLAN_SKIP,
            response_plan=JokeAdvice(comic_strategy=technique),
            identity_text=identity_text, identity_source="chat",
            identity_skipped=identity_skipped,
            style_skip="style_requests_absent", lessons_skip="lessons_absent",
            speech_skip="speech_absent", context_text=str(summary or ""),
            user_parts=(str(summary or ""),))
    except Exception:
        logger.warning("[meme] joke speech compose failed — база канала",
                       exc_info=True)
        return base, {"composer": "failed", "system_sha12": _text_sha12(base)}
    return system, _speech_facts(system, manifest, technique)


async def _default_joke(llm, summary: str, *, instruction: str,
                        chat_id: int | None = None, base_source: str = "",
                        job_id: str = "",
                        correlation_id: str = "") -> tuple[str, dict]:
    """Этап B: ОДИН LLM-вызов — выжимка превращается в короткий абсурдный прикол.

    System собирает единый речевой композер: прикол придумывает САМ персонаж
    (Core/Identity/Expression/базовая речь/юмор/приём/Style Policy), а
    редактируемый промпт и J-директива остаются заданием. Выжимка —
    аналитическая часть: она едет ТОЛЬКО user-сообщением.

    Возврат ``(текст, диагностика сборки)``: второй элемент пишется в
    ``facts.joke.speech`` журнала попыток. Нет клиента — честный
    ``RuntimeError`` (``joke_generation_failed``).
    """
    generate = getattr(llm, "generate", None) if llm is not None else None
    if generate is None:
        raise RuntimeError("joke_client_unavailable")
    body = str(summary or "").strip()
    system, speech = await _joke_system_prompt(
        chat_id, instruction=instruction, base_source=base_source,
        summary=body, job_id=job_id)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": body},
    ]
    raw = await asyncio.wait_for(
        generate(messages, temperature=0.8,
                 chat_id=int(chat_id) if chat_id is not None else None,
                 module="initiative", step="meme_joke",
                 correlation_id=str(correlation_id or
                                    uuid.uuid4().hex[:16])),
        timeout=JOKE_TIMEOUT_SECONDS)
    return str(raw or "").strip(), speech



async def _default_image(prompt: str, chat_id: int, job_id: str):
    from services.image_generation import generate
    result = await generate(prompt, chat_id=chat_id, correlation_id=job_id,
                            consume_budget=False)
    return type("ProviderResult", (), {
        "called": True,
        "ok": bool(getattr(result, "ok", False)),
        "reason": str(getattr(result, "reason", "") or ""),
        "content": getattr(result, "content", None),
        # §P0IM-PB-LLM: имя файла (формат) — существующее поле результата
        # провайдера; байты изображения в журнал не попадают.
        "filename": str(getattr(result, "filename", "") or ""),
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

    B1 (``arch/deferred-publication.md`` §4): ПЕРВЫМ делом этот же проход
    доставляет отложенные артефакты прошлых проходов (``deliver_deferred_all``)
    — существующий тик мема и есть драйвер ретрая, второго планировщика нет.
    """
    results: list[AttemptResult] = []
    delivery_kwargs = {name: kwargs[name] for name in (
        "ledger", "sender", "publish_gate", "publication", "claim_store",
        "chat_enabled", "initiative_enabled", "settings", "now", "now_ts",
        "tz_name", "tz_source", "rights_check", "source_check")
        if name in kwargs}
    try:
        deferred = await deliver_deferred_all(
            db, chat_ids=chat_ids, **delivery_kwargs)
    except Exception:
        logger.warning("[meme] deferred delivery phase raised — не валит "
                       "проход", exc_info=True)
        deferred = []
    for result in deferred:
        results.append(result)
        await _note_state(state, result, kwargs)
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
    # P0IM-BAN-NOETA: значение — только доказанная нижняя граница «последний
    # вызов провайдера + кулдаун». Без вызова (или без кулдауна) времени нет:
    # `now` в поле не подставляется, иначе проход выдаёт себя за расписание.
    next_check = None
    if cooldown > 0 and last_provider_ts > 0:
        candidate = int(last_provider_ts) + int(cooldown)
        if candidate > int(now_ts):
            next_check = candidate
    state[str(int(result.chat_id))] = {
        "output_kind": OUTPUT_KIND,
        "last_check_ts": int(now_ts),
        "next_check_ts": (None if next_check is None else int(next_check)),
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


def _last_joke(rows: list[dict]) -> dict:
    """Факты САМОГО СВЕЖЕГО ``joke``-ряда (витрина диагностики, без текстов).

    Порядок ``rows`` — свежие первыми (durable — ``ts DESC``, process-local —
    перевёрнутый кольцевой буфер), поэтому достаточно первой встреченной строки
    этапа B. Разбор — тем же единственным ``parse_attempt_facts``.
    """
    for row in rows:
        if str(row.get("stage") or "") == STAGE_JOKE:
            return parse_attempt_facts(row)
    return {}


def _last_events(rows: list[dict]) -> list[dict]:
    """События САМОЙ СВЕЖЕЙ попытки из журнала (§1.3, durable).

    Строки идут свежими вперёд; события лежат в терминальной строке её JSON
    фактов. Пусто → пустой список (витрина покажет «нет данных», не нули).
    """
    for row in rows:
        if str(row.get("stage") or "") not in STAGES:
            continue
        parsed = parse_attempt_facts(row)
        events = parsed.get("events")
        if isinstance(events, list) and events:
            return [dict(item) for item in events if isinstance(item, dict)]
    return []


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
        # MEME-JOKE-SPEECH: аддитивная диагностика свежего прикола (слои и
        # фактические ревизии) для карточки «Инициатива → Мемы».
        "last_joke": _last_joke(rows),
        # §1.3 P0: цепочка событий свежей попытки (source_snapshot →
        # image_ready → publication_*): генерация и доставка различимы.
        "events": _last_events(rows),
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
    cooldown = int(cfg.cooldown_seconds if cfg is not None else 0)
    remaining = 0
    if cooldown and last_check:
        remaining = max(0, cooldown - max(0, now - last_check))
    # P0IM-BAN-NOETA: только доказанная нижняя граница (последний вызов
    # провайдера + кулдаун, если она ещё в будущем). Никакого `now` вместо
    # времени: без вызова провайдера или без кулдауна — null.
    next_check = None
    if cooldown > 0 and last_check > 0:
        candidate = int(last_check) + int(cooldown)
        if candidate > int(now):
            next_check = candidate
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
        "next_check_ts": (None if next_check is None else int(next_check)),
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
