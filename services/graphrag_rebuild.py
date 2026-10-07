"""ASAP-3.2 (round1029, ADR-1028-5 D1–D3; T-4191/T-4192) — GraphRAG shadow
rebuild lifecycle: полный re-embed под текущим fingerprint → validation
(9 критериев §6) → атомарная активация.

RCA (spec §1): preexisting vec-таблицы → generation регистрируется `building`
(карантин B-MCA07-1/A06), backfill — «fill missing», НЕ rebuild, и НЕ имеет
перехода `building → active` → вечный FTS-only при `gen_fp == new_fp`.

Решение (D1 — вариант A, Accepted):
  * **shadow generation**: под текущим identity-fingerprint строится
    generation-suffixed shadow vec-хранилище (`{live}_g{generation}`) — полный
    re-embed ВСЕХ eligible source-фактов (НЕ fill-missing); existing vec-rows
    НЕ trusted (§5).
  * per-row provenance — по построению: все строки shadow принадлежат одному
    build'у (маркер принадлежности — в имени shadow/реестре поколений,
    RAW `graph_facts` не трогается, Q14).
  * **validation** — 9 критериев §6 (fingerprint/dim/provider-model/
    preprocessing/coverage/orphans/counts/KNN-smoke/swap), все обязаны быть
    true одновременно.
  * **atomic activate**: DROP live + CREATE live + копирование из shadow +
    переход реестра поколений — ОДНА транзакция (DDL в SQLite транзакционен;
    откат возвращает прежнюю live-таблицу). `UPDATE … SET status='active'`
    выполняется ТОЛЬКО здесь и ТОЛЬКО после проверки provenance ВСЕХ
    векторов (запрет §3/§66 соблюдён: shadow по построению несёт векторы,
    построенные этим build'ом под текущим fingerprint).
  * **resumable (D2)**: durable-состояние на REUSE `task_jobs` (v14, ΔDDL=0),
    state machine `queued → running → checkpoint → validated → activated |
    failed` (+`paused`/`cancelled` — §64 pause/resume/cancel); checkpoint
    (cursor по source-id) → продолжение после restart. bounded-батчи +
    sleep/yield + progress (§64); НЕ блокирует startup/polling (background
    fire-and-forget).
  * **race-guard (D2)**: build привязан к fingerprint, полученному на старте;
    при validate `current_fp != build_fp` → старый build НЕ активируется
    (`failed/fingerprint_changed`), shadow удаляется, под новый fp
    планируется новый build (§70).
  * embedding-кэш (64.4/MCA-07 D4) переиспользуется ТОЛЬКО при полном
    совпадении identity (§65) — переупаковка при неизменном конфиге БЕЗ
    повторных платных API-вызовов идёт через обычный `memory._embed`.
  * FTS — постоянный резерв: на всём протяжении build/validate/activate и
    после failed vector-path остаётся закрыт (`_index_generation_ok`), FTS
    обслуживает запросы (§62).

События (§6): `EMBEDDING_GENERATION_BUILD_START / PROGRESS / VALIDATED /
ACTIVATED` (+ failed) — через REUSE `emit_mca_event` (mca-13), R17-safe
(только индексы/счётчики/короткие fp-префиксы, без фактов/текстов).

Δ SQLite DDL = 0: shadow — идемпотентный `CREATE VIRTUAL TABLE IF NOT
EXISTS` (прецедент EXTRA/Фазы B); user_version НЕ меняется (v19; бронь v20
`mca-04b` не занимаем — Q14).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import struct
import time

logger = logging.getLogger(__name__)

# ── Состояния durable-джобы (D2; REUSE `task_jobs`, статусы — TEXT) ─────────
# ASAP-4 (T-4408, spec §1 A.5; AM-1 ADR-1028-7): расширенная машина §26 —
# 429/provider-quota → paused_rate_limit/paused_provider (НЕ terminal failed),
# build-fail валидации → validation_failed (vectors сохраняются, T-4409).
# Легаси-статусы (`running`/`checkpoint`) остаются валидными входами
# (существующие джобы/рестарты) и маппятся на building/checkpoint.
ST_QUEUED = "queued"
ST_BUILDING = "building"
ST_RUNNING = "running"           # legacy-алиас building (существующие джобы)
ST_CHECKPOINT = "checkpoint"
ST_PAUSED = "paused"             # операторская пауза — НЕ авто-resume
ST_PAUSED_RATE_LIMIT = "paused_rate_limit"   # 429 — авто-resume после cooldown
ST_PAUSED_PROVIDER = "paused_provider"       # provider unavailable — авто-resume
ST_VALIDATING = "validating"
ST_VALIDATED = "validated"
ST_VALIDATION_FAILED = "validation_failed"   # vectors сохранены (§29)
ST_ACTIVATED = "activated"
ST_ACTIVE = "active"             # §26-алиас (task_jobs хранит activated)
ST_FAILED = "failed"
ST_CANCELLED = "cancelled"

# Статусы, из которых джоба считается активной сборкой (lease/конкуренция).
BUILDING_STATUSES = frozenset({ST_BUILDING, ST_RUNNING, ST_CHECKPOINT,
                               ST_VALIDATING, ST_QUEUED})
# Паузы по quota/provider — авто-resume (AM-1); операторская `paused` — нет.
AUTO_RESUME_STATUSES = frozenset({ST_PAUSED_RATE_LIMIT, ST_PAUSED_PROVIDER})
# Статусы, из которых failure-классификатор (_handle_build_failure) имеет
# право переводить джобу (M-ASAP4-3): expect берётся от ФАКТИЧЕСКОГО статуса —
# исключение на пост-checkpoint стадии (validate/emit) больше не молчит как
# CAS-no-op. Вне множества (терминальные/паузы) expect=ST_RUNNING →
# безопасный no-op без ложных переходов.
_FAILURE_CAS_FROM = frozenset({ST_BUILDING, ST_RUNNING, ST_CHECKPOINT,
                               ST_VALIDATING, ST_VALIDATED})

_KIND = "graphrag_rebuild"
_OWNER = "memory"

# ── D10 (asap5-final-fixes, T-5255): future-resume переживает рестарты ──────
# RCA G2: `_ensure_job` при неистёкшем `next_allowed_at` даёт no-op БЕЗ
# планирования resume, а in-process auto-resume (`_schedule_auto_resume`)
# умирает вместе с процессом (рестарты прода ~1.3 ч). Лечение — БЕЗ in-process
# sleep: периодический scheduler-тик (период ≤ 15 мин, константа в коде)
# вызывает `maybe_schedule_rebuilds(include_failed=False)`; в окне cooldown
# `_ensure_job` даёт no-op, после истечения — следующий тик возобновляет job.
# Тик периодический → переживает рестарты by construction (durable-состояние
# в task_jobs/реестре не меняется).
RESUME_TICK_SECONDS = 900          # ≤ 15 мин (D10)
_resume_ticker_started = False

# Спецификация индексов: source (source of truth, НЕ удалять — R18), live
# vec-таблица, колонки копирования (int8-вариант добавляет embedding_i8).
_INDEX_SPECS: dict[str, dict] = {
    "graph_facts_vec": {
        "source": "graph_facts",
        "source_cols": "id, fact, chat_id, origin, expires_at",
        "eligible_ts": True,          # expires_at IS NULL OR expires_at > now
        "live": "graph_facts_vec",
        "copy_cols": "rowid, fact_id, chat_id, origin, expires_at, embedding",
        "insert_cols": "rowid, fact_id, chat_id, origin, expires_at, embedding",
    },
    "smart_archive": {
        "source": "smart_archive_facts",
        "source_cols": "id, fact, chat_id",
        "eligible_ts": False,
        "live": "smart_archive",
        "copy_cols": "rowid, fact_id, chat_id, embedding",
        "insert_cols": "rowid, fact_id, chat_id, embedding",
    },
}

_FLOAT_DIM_RE = re.compile(r"float\[(\d+)\]")

# running-джоба без свежего heartbeat дольше этого — takeover-кандидат
# (restart прошлого процесса).
_STALE_RUNNING_SECONDS = 600


def graphrag_rebuild_enabled() -> bool:
    """Kill-switch `GRAPHRAG_SHADOW_REBUILD_ENABLED` (env-only, default ON).

    OFF → прежний lifecycle (building-карантин + backfill-fill-missing),
    байт-в-байт паритет 2.58.39 (rollback §80)."""
    try:
        from config.settings import settings
        return bool(getattr(settings, "GRAPHRAG_SHADOW_REBUILD_ENABLED", True))
    except Exception:      # pragma: no cover — защитная ветка
        return True


def _batch_size() -> int:
    try:
        from config.settings import settings
        return max(1, int(getattr(settings, "GRAPHRAG_REBUILD_BATCH", 50)))
    except Exception:      # pragma: no cover
        return 50


def _sleep_seconds() -> float:
    try:
        from config.settings import settings
        value = float(getattr(settings, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.5))
    except Exception:      # pragma: no cover
        value = 0.5
    return max(0.0, min(value, 60.0))


# ── ASAP-4 (T-4406/T-4408): adaptive batch + retry horizon + классификация ──


def _adaptive_batch_size() -> int:
    """Adaptive batch (spec §20): при EMBED_ADAPTIVE_CONCURRENCY_ENABLED=ON —
    AIMD-значение контроллера (границы EMBED_BATCH_MIN/MAX, старт 32–50);
    OFF → статический GRAPHRAG_REBUILD_BATCH (бит-в-бит)."""
    try:
        from services.embedding_control_plane import (adaptive_concurrency_enabled,
                                                      CONTROLLER)
        if adaptive_concurrency_enabled():
            return max(1, CONTROLLER.batch_size)
    except Exception:      # pragma: no cover
        pass
    return _batch_size()


def _rebuild_priority():
    """P3 (full rebuild) для контрол-плейна; None → дефолт контекста."""
    try:
        from services.embedding_control_plane import Priority
        return Priority.P3_REBUILD
    except Exception:      # pragma: no cover
        return None


def _control_plane_on() -> bool:
    try:
        from services.embedding_control_plane import control_plane_enabled
        return control_plane_enabled()
    except Exception:      # pragma: no cover
        return False


def _is_rate_limit_exception(exc: Exception) -> bool:
    """429-класс (AM-1: paused_rate_limit, НЕ terminal failed)."""
    name = type(exc).__name__
    if "RateLimit" in name:
        return True
    return "429" in str(exc)[:200]


def _is_provider_unavailable(exc: Exception) -> bool:
    """5xx/timeout/transport класс (paused_provider; lease не теряется)."""
    name = type(exc).__name__
    return any(mark in name for mark in
               ("Server", "Timeout", "Transport", "Connection"))


def _is_auth_exception(exc: Exception) -> bool:
    return "Auth" in type(exc).__name__


def _retry_horizon_seconds() -> float:
    """§25: bounded retry horizon (wall-clock pause-циклов), default 24h —
    исчерпание → terminal FAILED."""
    try:
        from config.settings import settings
        return max(0.1, float(getattr(settings, "EMBED_RETRY_HORIZON_HOURS",
                                      24.0))) * 3600.0
    except Exception:      # pragma: no cover
        return 24.0 * 3600.0


def _default_cooldown_s() -> float:
    """Дефолт-кулдаун (developer bound) для пауз без provider-сигнала."""
    try:
        from config.settings import settings
        return max(1.0, float(getattr(
            settings, "EMBED_RATE_LIMIT_DEFAULT_COOLDOWN_SECONDS", 20.0)))
    except Exception:      # pragma: no cover
        return 20.0


def _resume_backoff_enabled() -> bool:
    """D2 (T-4503): kill-switch `EMBED_RESUME_BACKOFF_ENABLED` (env-only,
    default ON). OFF → задержки resume без нелинейности (бит-в-бит 2.58.45)."""
    try:
        from services.embedding_control_plane import resume_backoff_enabled
        return resume_backoff_enabled()
    except Exception:      # pragma: no cover — fail-open ON (как `_flag`)
        return True


def _resume_backoff_max_s() -> float:
    """D2: потолок нелинейного backoff (`EMBED_RESUME_BACKOFF_MAX_SECONDS`,
    default 3600)."""
    try:
        from config.settings import settings
        return max(1.0, float(getattr(
            settings, "EMBED_RESUME_BACKOFF_MAX_SECONDS", 3600.0)))
    except Exception:      # pragma: no cover
        return 3600.0


def _resume_backoff_delay(streak: int) -> float:
    """D2 (T-4503): нелинейный backoff auto-resume —
    `min(default × 2^streak, MAX=3600) × jitter(1.00–1.25)`.

    Применяется ТОЛЬКО к паузам без provider-горизонта (kind unknown/tpm без
    RA / default-cooldown ветка CoolingDown); поверх parking-горизонта backoff
    не наслаивается (resume строго на next_allowed_at). Флаг OFF →
    дефолт-кулдаун без нелинейности и без джиттера (бит-в-бит)."""
    if not _resume_backoff_enabled():
        return _default_cooldown_s()
    base = _default_cooldown_s() * (2 ** max(0, int(streak)))
    delay = min(base, _resume_backoff_max_s())
    return delay * (1.0 + random.random() * 0.25)


async def _quota_streak(db, job_id: str) -> int:
    """D2: `quota_exhaust_streak` из `result_ref` (толерантный парсер:
    битый/чужой JSON или нет ключа → 0; старые строки совместимы)."""
    try:
        cursor = await db.db.execute(
            "SELECT result_ref FROM task_jobs WHERE job_id = ?", (job_id,))
        row = await cursor.fetchone()
        raw = str(row["result_ref"]) if row is not None else ""
        data = json.loads(raw or "{}")
        if isinstance(data, dict):
            return max(0, int(data.get("quota_exhaust_streak") or 0))
    except (ValueError, TypeError, KeyError):
        pass
    except Exception:
        logger.warning("graphrag rebuild: quota streak read failed",
                       exc_info=True)
    return 0


async def _clear_quota_streak(db, job_id: str) -> None:
    """D2: первый успешный батч после resume обнуляет
    `quota_exhaust_streak` (fail-open; пишется только если стрик был > 0 —
    без лишних записей на каждый батч)."""
    try:
        cursor = await db.db.execute(
            "SELECT result_ref FROM task_jobs WHERE job_id = ?", (job_id,))
        row = await cursor.fetchone()
        raw = str(row["result_ref"]) if row is not None else ""
        try:
            data = json.loads(raw or "{}")
        except ValueError:
            return
        if not isinstance(data, dict):
            return
        if not int(data.get("quota_exhaust_streak") or 0):
            return
        data["quota_exhaust_streak"] = 0
        now = int(time.time())

        async def _body(conn):
            await conn.execute(
                "UPDATE task_jobs SET result_ref = ?, updated_at = ? "
                "WHERE job_id = ?",
                (json.dumps(data, ensure_ascii=False), now, job_id))

        await db.write_transaction(_body, op_name="graphrag_quota_streak_reset")
    except Exception:
        logger.warning("graphrag rebuild: quota streak reset failed",
                       exc_info=True)


def _quota_kind_of_pause(reason: str, exc: Exception | None = None) -> str:
    """D2-диагностика: kind последней quota-паузы для
    `result_ref.quota_kind_last` (честно: из registry-ноты группы или
    reason-суффикса; без фальшивой точности)."""
    if reason == "rate_limit:quota_group":
        gid = str(getattr(exc, "group_id", "") or "")
        if gid:
            try:
                from services.embedding_control_plane import (
                    REGISTRY as ECP_REGISTRY)
                note = ECP_REGISTRY.group_state(gid).note
            except Exception:      # pragma: no cover — fail-open
                note = ""
            match = re.search(r"kind=([a-z_]+)", note or "")
            if match:
                return match.group(1)[:24]
        return "quota_group"
    if reason.startswith("rate_limit:"):
        return (reason.split(":", 1)[1] or "unknown")[:24]
    return ""


async def _registry_pause(db, index_name: str, fp: str, reason: str,
                          next_allowed_at: int) -> None:
    """AM-1: pause-колонки реестра поколений (v23 additive:
    pause_reason/next_allowed_at/attempts_total). Fail-open."""
    try:
        now = int(time.time())

        async def _body(conn):
            await conn.execute(
                "UPDATE mca_embedding_index_generations SET pause_reason = ?, "
                "next_allowed_at = ?, attempts_total = COALESCE"
                "(attempts_total, 0) + 1 WHERE index_name = ? AND "
                "fingerprint = ? AND status = 'building'",
                (reason[:64], int(next_allowed_at), index_name, fp))

        await db.write_transaction(_body, op_name="graphrag_pause_registry")
    except Exception:
        logger.warning("graphrag rebuild: registry pause update failed",
                       exc_info=True)


async def _registry_resume(db, index_name: str, fp: str) -> None:
    try:
        now = int(time.time())

        async def _body(conn):
            await conn.execute(
                "UPDATE mca_embedding_index_generations SET pause_reason = "
                "NULL, next_allowed_at = NULL WHERE index_name = ? AND "
                "fingerprint = ? AND status = 'building'",
                (index_name, fp))

        await db.write_transaction(_body, op_name="graphrag_resume_registry")
    except Exception:
        logger.warning("graphrag rebuild: registry resume update failed",
                       exc_info=True)


async def _pause_bookkeeping(db, job_id: str, reason: str,
                             next_allowed_at: int, *,
                             quota_streak: int | None = None,
                             quota_kind: str | None = None) -> None:
    """Пауза-метаданные в `result_ref` (REUSE, ΔDDL=0): pause_started_at для
    horizon §25 + счётчик пауз. Существующие строки НЕ мигрируются.
    D2 (T-4503): + `quota_exhaust_streak` (подряд exhausted-пауз без
    успешного батча; инкремент считает CALLER и только для exhausted-класса)
    + `quota_kind_last` (диагностика). Толерантный парсер — старые строки
    совместимы, отсутствие ключей = стрик 0."""
    try:
        cursor = await db.db.execute(
            "SELECT result_ref FROM task_jobs WHERE job_id = ?", (job_id,))
        row = await cursor.fetchone()
        raw = str(row["result_ref"]) if row is not None else ""
        try:
            bookkeeping = json.loads(raw or "{}")
        except ValueError:
            bookkeeping = {}
        if not isinstance(bookkeeping, dict):
            bookkeeping = {}
        if "pause_started_at" not in bookkeeping:
            bookkeeping = {"pause_started_at": int(time.time()),
                           "pause_count": int(bookkeeping.get("pause_count") or 0)}
        bookkeeping["pause_count"] = int(bookkeeping.get("pause_count") or 0) + 1
        bookkeeping["last_pause_reason"] = reason[:64]
        bookkeeping["next_allowed_at"] = int(next_allowed_at)
        if quota_streak is not None:
            bookkeeping["quota_exhaust_streak"] = max(0, int(quota_streak))
        if quota_kind:
            bookkeeping["quota_kind_last"] = str(quota_kind)[:24]
        now = int(time.time())

        async def _body(conn):
            await conn.execute(
                "UPDATE task_jobs SET result_ref = ?, updated_at = ? "
                "WHERE job_id = ?",
                (json.dumps(bookkeeping, ensure_ascii=False), now, job_id))

        await db.write_transaction(_body, op_name="graphrag_pause_bookkeeping")
    except Exception:
        logger.warning("graphrag rebuild: pause bookkeeping failed",
                       exc_info=True)


async def _pause_started_at(db, job_id: str) -> int:
    try:
        cursor = await db.db.execute(
            "SELECT result_ref FROM task_jobs WHERE job_id = ?", (job_id,))
        row = await cursor.fetchone()
        raw = str(row["result_ref"]) if row is not None else ""
        data = json.loads(raw or "{}")
        if isinstance(data, dict):
            return int(data.get("pause_started_at") or 0)
    except (ValueError, TypeError, KeyError):
        pass
    except Exception:
        logger.warning("graphrag rebuild: pause bookkeeping read failed",
                       exc_info=True)
    return 0


async def _horizon_exhausted(db, job_id: str) -> bool:
    """§25: wall-clock pause-горизонт исчерпан → terminal FAILED."""
    started = await _pause_started_at(db, job_id)
    if not started:
        return False
    return (int(time.time()) - started) >= _retry_horizon_seconds()


async def resume_tick_once(memory) -> list[str]:
    """D10/T-5255: один тик future-resume — `maybe_schedule_rebuilds` с
    include_failed=False (bounded retry: failure-класс не переоткрывается
    тиком, только startup/явный триггер). Отдельная функция — для тикера
    и тестов (симуляция рестарта = новый вызов после истечения cooldown)."""
    return await maybe_schedule_rebuilds(memory, include_failed=False)


def start_resume_ticker(memory) -> bool:
    """D10/T-5255: запустить периодический тик future-resume (один на
    процесс; идемпотентно). Никогда не бросает; возвращает факт старта.
    Warning НЕ глушится — guard `_index_generation_ok` продолжает честно
    предупреждать, тик лишь устраняет resume-gap (RCA G2/G3)."""
    global _resume_ticker_started
    if _resume_ticker_started:
        return False
    if not graphrag_rebuild_enabled():
        return False
    _resume_ticker_started = True

    async def _loop():
        while True:
            await asyncio.sleep(RESUME_TICK_SECONDS)
            try:
                await resume_tick_once(memory)
            except Exception:      # тик живёт дольше любого сбоя
                logger.warning("graphrag rebuild: resume tick failed",
                               exc_info=True)

    try:
        from services.summary_memory import fire_and_forget
        fire_and_forget(_loop(), "graphrag_resume_ticker")
    except Exception:      # pragma: no cover
        asyncio.ensure_future(_loop())
    logger.info("graphrag rebuild: resume ticker started | period_s=%d",
                RESUME_TICK_SECONDS)
    return True


def _schedule_auto_resume(memory, db, index_name: str, delay_s: float) -> None:
    """AM-1: авто-resume после cooldown — fire-and-forget задача переводит
    paused_rate_limit/paused_provider → queued и пере-schedule'ит (restart-
    устойчиво: до рестарта добирает `maybe_schedule_rebuilds`)."""
    async def _resume_later():
        try:
            await asyncio.sleep(max(1.0, min(float(delay_s), 6 * 3600.0)))
            job = await _find_active_job(db, index_name,
                                         await _current_fp_async(db, index_name) or "")
            if job is None:
                return
            status = str(job.get("status") or "")
            if status not in AUTO_RESUME_STATUSES:
                return
            # Коулдаун мог продлиться новыми 429 — сверяемся с реестром.
            gen = await db.get_generation_by_fingerprint(
                index_name, str(job.get("coalesce_key") or "").split(":")[-1])
            next_allowed = int((gen or {}).get("next_allowed_at") or 0)
            if next_allowed and int(time.time()) < next_allowed:
                _schedule_auto_resume(memory, db, index_name,
                                      next_allowed - int(time.time()))
                return
            await _job_cas(db, str(job["job_id"]), expect=status,
                           set_status=ST_QUEUED,
                           reason_code="cooldown_expired")
            await _registry_resume(db, index_name,
                                   str(job.get("coalesce_key") or "").split(":")[-1])
            await maybe_schedule_rebuilds(memory)
        except Exception:
            logger.warning("graphrag rebuild: auto-resume failed | index=%s",
                           index_name, exc_info=True)

    try:
        from services.summary_memory import fire_and_forget
        fire_and_forget(_resume_later(), f"graphrag_resume:{index_name}")
    except Exception:      # pragma: no cover
        asyncio.ensure_future(_resume_later())


def _emit(event_name: str, outcome: str, *, level: str = "info", **fields):
    """Fail-open эмиссия EMBEDDING_GENERATION_* (§6; REUSE mca-13). R17-safe:
    только index/generation/счётчики/короткие fp."""
    try:
        from services.mca_events import emit_mca_event
        emit_mca_event(event_name, outcome=outcome, level=level,
                       component="graphrag_rebuild", **fields)
    except Exception:      # контракт не рвёт поток
        pass


def _fp12(fp: str) -> str:
    return str(fp or "")[:12]


# ── task_jobs helpers (кастомные статусы D2 поверх v14-таблицы) ─────────────

async def _get_job(db, job_id: str) -> dict | None:
    try:
        cursor = await db.db.execute(
            "SELECT * FROM task_jobs WHERE job_id = ?", (job_id,))
        row = await cursor.fetchone()
        return dict(row) if row is not None else None
    except Exception:
        return None


async def _job_cas(db, job_id: str, *, expect: str, set_status: str,
                   reason_code: str | None = None,
                   terminal: bool = False) -> bool:
    """CAS-переход статуса durable-джобы (одновательный single-writer).

    Терминальные переходы (`activated`/`failed`/`cancelled`) проставляют
    `finished_at` — bounded-очистка v14 (`prune`) их увидит."""
    now = int(time.time())

    async def _body(conn):
        if terminal:
            cursor = await conn.execute(
                "UPDATE task_jobs SET status = ?, "
                "reason_code = COALESCE(?, reason_code), finished_at = ?, "
                "updated_at = ? WHERE job_id = ? AND status = ?",
                (set_status, reason_code, now, now, job_id, expect))
        else:
            cursor = await conn.execute(
                "UPDATE task_jobs SET status = ?, "
                "reason_code = COALESCE(?, reason_code), updated_at = ? "
                "WHERE job_id = ? AND status = ?",
                (set_status, reason_code, now, job_id, expect))
        return cursor.rowcount

    try:
        return bool(await db.write_transaction(
            _body, op_name="graphrag_rebuild_cas"))
    except Exception:
        logger.warning("graphrag rebuild: CAS failed | job=%s | %s→%s",
                       job_id, expect, set_status, exc_info=True)
        return False


def _coalesce_key(index_name: str, fp: str) -> str:
    return f"{_KIND}:{index_name}:{fp}"


async def _find_active_job(db, index_name: str, fp: str) -> dict | None:
    try:
        cursor = await db.db.execute(
            "SELECT * FROM task_jobs WHERE kind = ? AND coalesce_key = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (_KIND, _coalesce_key(index_name, fp)))
        row = await cursor.fetchone()
        return dict(row) if row is not None else None
    except Exception:
        return None


# ── shadow-хранилище ────────────────────────────────────────────────────────

def _shadow_name(index_name: str, generation: int) -> str:
    return f"{_INDEX_SPECS[index_name]['live']}_g{int(generation)}"


def _live_ddl(memory, index_name: str) -> str:
    """Канонический DDL live-таблицы (тот же формат, что у MemoryManager)."""
    dim = int(memory._vec_dim or 0)
    if index_name == "graph_facts_vec":
        return memory._graph_vec_table_sql(dim)
    return memory._vec_table_sql(dim)


async def _create_shadow(memory, index_name: str, shadow: str) -> None:
    """Идемпотентный CREATE VIRTUAL TABLE IF NOT EXISTS (ΔDDL = 0, Q14)."""
    live = _INDEX_SPECS[index_name]["live"]
    sql = _live_ddl(memory, index_name).replace(
        f"IF NOT EXISTS {live}", f"IF NOT EXISTS {shadow}")
    async with memory.db.serialized():
        await memory.db.db.execute(sql)
        await memory.db.db.commit()


async def _drop_shadow(memory, shadow: str) -> None:
    try:
        async with memory.db.serialized():
            await memory.db.db.execute(f"DROP TABLE IF EXISTS {shadow}")
            await memory.db.db.commit()
    except Exception:
        logger.warning("graphrag rebuild: shadow drop failed | %s", shadow,
                       exc_info=True)


# ── партии source-фактов (cursor-based полный скан — НЕ fill-missing) ───────

async def _fetch_batch(memory, spec: dict, last_id: int) -> list[dict]:
    now = int(time.time())
    sql = (f"SELECT {spec['source_cols']} FROM {spec['source']} "
           f"WHERE id > ? ")
    params: list = [int(last_id)]
    if spec["eligible_ts"]:
        sql += "AND (expires_at IS NULL OR expires_at > ?) "
        params.append(now)
    sql += "ORDER BY id LIMIT ?"
    # ASAP-4 (§20): adaptive batch (AIMD по 429/latency, границы env) при ON;
    # статический GRAPHRAG_REBUILD_BATCH при OFF (бит-в-бит).
    params.append(_adaptive_batch_size())
    cursor = await memory.db.db.execute(sql, tuple(params))
    return [dict(r) for r in await cursor.fetchall()]


async def _insert_shadow_rows(memory, spec: dict, shadow: str,
                              batch: list[dict], vectors: list) -> int:
    """Вставка пачки в shadow (rowid = fact_id, полный re-embed — существующие
    live-строки НЕ re-used; повтор на resume перекрывается existence-check)."""
    int8 = bool(memory._vec_int8)
    inserted = 0
    async with memory.db.serialized():
        for row, vector in zip(batch, vectors):
            if not vector:
                continue
            cursor = await memory.db.db.execute(
                f"SELECT rowid FROM {shadow} WHERE rowid = ?", (row["id"],))
            if await cursor.fetchone() is not None:
                continue
            if int8:
                await memory.db.db.execute(
                    f"INSERT INTO {shadow}(rowid, fact_id, chat_id, origin, "
                    "expires_at, embedding, embedding_i8) "
                    "VALUES (?, ?, ?, ?, ?, ?, vec_quantize_int8(?, 'unit'))",
                    (row["id"], row["id"], row["chat_id"], row["origin"],
                     row["expires_at"], json.dumps(vector),
                     json.dumps(vector)))
            elif "origin" in row:
                await memory.db.db.execute(
                    f"INSERT INTO {shadow}(rowid, fact_id, chat_id, origin, "
                    "expires_at, embedding) VALUES (?, ?, ?, ?, ?, ?)",
                    (row["id"], row["id"], row["chat_id"], row["origin"],
                     row["expires_at"], json.dumps(vector)))
            else:
                await memory.db.db.execute(
                    f"INSERT INTO {shadow}(rowid, fact_id, chat_id, embedding)"
                    " VALUES (?, ?, ?, ?)",
                    (row["id"], row["id"], row["chat_id"],
                     json.dumps(vector)))
            inserted += 1
        await memory.db.db.commit()
    return inserted


# ── validation (9 критериев §6; T-4192) ─────────────────────────────────────

def _read_vector(blob) -> list[float] | None:
    try:
        if isinstance(blob, str):
            data = json.loads(blob)
            return [float(x) for x in data] if isinstance(data, list) else None
        raw = bytes(blob)
        return list(struct.unpack(f"<{len(raw) // 4}f", raw))
    except Exception:
        return None


async def _validate(memory, index_name: str, shadow: str, fp: str,
                    frontier: int) -> tuple[bool, dict]:
    """Критерии §6 (1–8; №9 — сама транзакция swap). Возвращает
    ``(ok, report)``; report — R17-safe (числа/bool/короткие коды)."""
    spec = _INDEX_SPECS[index_name]
    report: dict = {"index": index_name, "shadow": shadow,
                    "frontier": int(frontier), "criteria": {}}
    crit = report["criteria"]
    now = int(time.time())

    # 1. fingerprint == current (race-guard D2 — первый и самый дешёвый).
    current_fp = memory._identity_fingerprint()
    crit["fingerprint_current"] = (fp == current_fp)
    if fp != current_fp:
        report["reason_code"] = "fingerprint_changed"
        report["build_fp"] = _fp12(fp)
        report["current_fp"] = _fp12(current_fp)
        return False, report

    # 2. dim == current (DDL shadow).
    cursor = await memory.db.db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (shadow,))
    row = await cursor.fetchone()
    stored_dim = None
    if row and row["sql"]:
        match = _FLOAT_DIM_RE.search(row["sql"])
        if match:
            stored_dim = int(match.group(1))
    crit["dim_current"] = (stored_dim is not None
                           and stored_dim == int(memory._vec_dim or -1))
    if not crit["dim_current"]:
        report["reason_code"] = "dim_changed"
        report["shadow_dim"] = stored_dim
        return False, report

    # 3/4. provider/model identity + preprocessing_version == текущий config.
    gen = await memory.db.get_generation_by_fingerprint(index_name, fp)
    from services import summary_memory as sm
    want_provider = sm._embedding_provider()
    want_model = None
    try:
        from services import hot_config as hot
        from config.settings import settings
        want_model = hot.get("models.embedding_model_name",
                             settings.EMBEDDING_MODEL_NAME)
    except Exception:      # pragma: no cover — конфиг не роняет validation
        want_model = None
    want_preproc = sm.EMBEDDING_PREPROCESSING_VERSION
    got = gen or {}
    crit["provider_model_current"] = (
        str(got.get("provider") or "") == str(want_provider or "")
        and str(got.get("model") or "") == str(want_model or ""))
    crit["preprocessing_current"] = (
        str(got.get("preprocessing_version") or "") == str(want_preproc))
    if not (crit["provider_model_current"] and crit["preprocessing_current"]):
        report["reason_code"] = "identity_changed"
        return False, report

    # 5–7. coverage/orphans/counts.
    if spec["eligible_ts"]:
        cursor = await memory.db.db.execute(
            f"SELECT COUNT(*) AS c FROM {spec['source']} WHERE id <= ? "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (int(frontier), now))
    else:
        cursor = await memory.db.db.execute(
            f"SELECT COUNT(*) AS c FROM {spec['source']} WHERE id <= ?",
            (int(frontier),))
    eligible_total = int((await cursor.fetchone())["c"])

    sql_covered = (f"SELECT COUNT(*) AS c FROM {shadow} WHERE fact_id IN "
                   f"(SELECT id FROM {spec['source']} WHERE id <= ? ")
    params_covered: list = [int(frontier)]
    if spec["eligible_ts"]:
        sql_covered += "AND (expires_at IS NULL OR expires_at > ?) "
        params_covered.append(now)
    sql_covered += ")"
    cursor = await memory.db.db.execute(sql_covered, tuple(params_covered))
    covered = int((await cursor.fetchone())["c"])

    cursor = await memory.db.db.execute(
        f"SELECT COUNT(*) AS c FROM {shadow} WHERE fact_id NOT IN "
        f"(SELECT id FROM {spec['source']})")
    orphans_in_shadow = int((await cursor.fetchone())["c"])

    added_after_scan = 0
    if spec["eligible_ts"]:
        cursor = await memory.db.db.execute(
            f"SELECT COUNT(*) AS c FROM {spec['source']} WHERE id > ? "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (int(frontier), now))
    else:
        cursor = await memory.db.db.execute(
            f"SELECT COUNT(*) AS c FROM {spec['source']} WHERE id > ?",
            (int(frontier),))
    added_after_scan = int((await cursor.fetchone())["c"])

    missing_bad = max(0, eligible_total - covered)
    report.update({
        "eligible_total": eligible_total, "covered": covered,
        "missing": missing_bad,
        "allowed_missing_added_after_scan": added_after_scan,
        "orphans_excluded": orphans_in_shadow,
    })
    # 5: каждый eligible факт (id <= frontier) имеет vector row; факты,
    # добавленные ПОСЛЕ конца скана, — явно классифицированная допустимая
    # причина отсутствия (`added_after_scan`, закрываются обычным backfill).
    crit["coverage"] = (missing_bad == 0)
    # 6: в АКТИВИРУЕМЫЙ индекс попадают только строки с живым source-фактом
    # (анти-join в swap) → orphan vectors в новой live-таблице = 0 по
    # построению; строки-сироты в shadow исключаются и считаются в отчёте.
    crit["no_orphans"] = True
    # 7: count/coverage validation (объём копии == eligible-набору).
    crit["counts_match"] = (covered == eligible_total)
    if not (crit["coverage"] and crit["counts_match"]):
        report["reason_code"] = "missing_vectors"
        return False, report

    # 8. sample KNN smoke по SHADOW (self-match: косинус вектора с самим
    # собой == максимум → факт обязан вернуться в top-k).
    # ASAP-4 (T-4409, spec §1 A.6): distinct reason codes вместо generic
    # `knn_smoke_failed` (прод-факт Q10: пустой source был неотличим от
    # битого индекса) + R17-safe диагностика (counts/dim/stage — БЕЗ raw
    # fact text).
    diag: dict = {"index": index_name, "shadow": shadow, "stage": "knn_smoke"}
    cursor = await memory.db.db.execute(
        f"SELECT COUNT(*) AS c FROM {spec['source']}")
    diag["source_count"] = int((await cursor.fetchone())["c"])
    cursor = await memory.db.db.execute(f"SELECT COUNT(*) AS c FROM {shadow}")
    diag["vector_count"] = int((await cursor.fetchone())["c"])
    diag["expected_dim"] = int(memory._vec_dim or 0)
    diag["gen_fp"] = _fp12(fp)
    diag["vec_extension"] = bool(memory._vec_available)
    diag["query_vector_ok"] = False
    diag["executed"] = False
    diag["returned_rows"] = 0
    report["knn_diagnostics"] = diag

    if diag["source_count"] == 0:
        report["reason_code"] = "knn_source_empty"
        report["reason_detail"] = (
            f"source={spec['source']} rows=0 — векторизация не требуется, "
            "проверка на пустом источнике")
        crit["knn_smoke"] = False
        return False, report
    if not memory._vec_available:
        report["reason_code"] = "knn_vec_extension_missing"
        crit["knn_smoke"] = False
        return False, report
    if diag["vector_count"] == 0:
        report["reason_code"] = "knn_zero_results"
        diag["stage"] = "pre_query_count"
        crit["knn_smoke"] = False
        return False, report

    smoke_ok = False
    offset = random.randint(0, max(0, diag["vector_count"] - 1))
    cursor = await memory.db.db.execute(
        f"SELECT rowid, embedding FROM {shadow} LIMIT 1 OFFSET ?",
        (offset,))
    sample = await cursor.fetchone()
    vector: list[float] | None = None
    if sample is None:
        report["reason_code"] = "knn_index_schema_mismatch"
        diag["stage"] = "sample_fetch"
        crit["knn_smoke"] = False
        return False, report
    vector = _read_vector(sample["embedding"])
    if not vector:
        report["reason_code"] = "knn_row_corrupt"
        diag["stage"] = "sample_decode"
        diag["actual_dim"] = 0
        crit["knn_smoke"] = False
        return False, report
    diag["actual_dim"] = len(vector)
    if len(vector) != diag["expected_dim"]:
        report["reason_code"] = "knn_dim_mismatch"
        diag["stage"] = "sample_decode"
        crit["knn_smoke"] = False
        return False, report
    # M-ASAP4-4: построение query-вектора — отдельный узкий except: провал
    # сборки вектора (несериализуемый blob, битая проекция) — distinct
    # `knn_query_vector_failed`, НЕ маскируется под `knn_index_schema_mismatch`
    # (тот диагностирует сбой самого MATCH-запроса ниже).
    try:
        query_blob = json.dumps(vector)
    except Exception:
        logger.warning("graphrag rebuild: KNN query vector build failed | %s",
                       shadow, exc_info=True)
        report["reason_code"] = "knn_query_vector_failed"
        diag["stage"] = "query_vector_build"
        diag["query_vector_ok"] = False
        crit["knn_smoke"] = False
        return False, report
    diag["query_vector_ok"] = True
    try:
        cursor = await memory.db.db.execute(
            f"SELECT rowid FROM {shadow} WHERE embedding MATCH ? "
            "AND k = 5", (query_blob,))
        rows_out = await cursor.fetchall()
        ids = {r["rowid"] for r in rows_out}
        diag["executed"] = True
        diag["returned_rows"] = len(ids)
        smoke_ok = sample["rowid"] in ids
    except Exception:
        logger.warning("graphrag rebuild: KNN smoke failed | %s",
                       shadow, exc_info=True)
        report["reason_code"] = "knn_index_schema_mismatch"
        diag["stage"] = "knn_query"
        crit["knn_smoke"] = False
        return False, report
    if not smoke_ok:
        # Запрос выполнен, self-match не вернулся: distance-sanity (валидный
        # self-match должен дать distance ≈ 0) — diagnose как zero/corrupt.
        if diag["returned_rows"] == 0:
            report["reason_code"] = "knn_zero_results"
        else:
            report["reason_code"] = "knn_row_corrupt"
            diag["distance_sanity"] = "self_match_missing"
        diag["stage"] = "self_match"
        crit["knn_smoke"] = False
        return False, report
    diag["distance_sanity"] = "ok"
    crit["knn_smoke"] = True
    return True, report


# ── атомарная активация (§6.9; запрет §3/§66 соблюдён — см. docstring) ──────

async def _activate(memory, index_name: str, shadow: str, fp: str,
                    generation: int) -> bool:
    spec = _INDEX_SPECS[index_name]
    live = spec["live"]
    int8 = bool(memory._vec_int8)
    insert_cols = spec["insert_cols"] + (", embedding_i8" if int8 else "")
    copy_cols = spec["copy_cols"] + (", embedding_i8" if int8 else "")
    live_sql = _live_ddl(memory, index_name)
    now = int(time.time())

    async def _body(conn):
        # M-ASAP32-2: re-check fp ВНУТРИ транзакции — закрывает race-окно
        # validate→activate при hot-смене embedding-конфига (rollback →
        # activation_failed, shadow цел, self-heal на следующем schedule).
        if memory._identity_fingerprint() != fp:
            raise RuntimeError("fingerprint_changed")
        # 1. Прежняя live-таблица (unknown-origin vectors) заменяется ЦЕЛИКОМ;
        #    raw `graph_facts`/`smart_archive_facts` НЕ трогаются (source of
        #    truth, R18). DDL в SQLite транзакционен: откат возвращает прежнюю
        #    таблицу (FTS оставался serviceable всё время).
        await conn.execute(f"DROP TABLE IF EXISTS {live}")
        await conn.execute(live_sql)
        # 2. Копирование ТОЛЬКО строк с живым source-фактом (анти-orphan).
        await conn.execute(
            f"INSERT INTO {live}({insert_cols}) SELECT {copy_cols} "
            f"FROM {shadow} WHERE fact_id IN "
            f"(SELECT id FROM {spec['source']})")
        # 3. Реестр поколений (v18): прежнее активное → superseded; build'овое
        #    поколение → active. UPDATE допускается ТОЛЬКО после проверки
        #    provenance всех векторов (критерии 1–8 пройдены выше — §3/§66).
        #    ASAP 6 §8.1: live-таблицы физически принадлежат namespace
        #    'default' — supersede НЕ должен задевать ACTIVE других
        #    namespace (per-chat override, инвариант (namespace, index)).
        await conn.execute(
            "UPDATE mca_embedding_index_generations SET status = 'superseded',"
            " superseded_at = ? WHERE index_name = ? AND namespace = 'default'"
            " AND status = 'active' AND fingerprint != ?",
            (now, index_name, fp))
        cursor = await conn.execute(
            "UPDATE mca_embedding_index_generations SET status = 'active', "
            "activated_at = ? WHERE index_name = ? AND generation = ? AND "
            "fingerprint = ? AND status IN ('building', 'validated')",
            (now, index_name, int(generation), fp))
        if cursor.rowcount != 1:
            raise RuntimeError("generation_row_missing")
        # 4. Shadow больше не нужен (данные в live).
        await conn.execute(f"DROP TABLE IF EXISTS {shadow}")

    try:
        await memory.db.write_transaction(
            _body, op_name="graphrag_rebuild_activate")
        return True
    except Exception:
        logger.error("graphrag rebuild: activation failed | index=%s | %s",
                     index_name, shadow, exc_info=True)
        return False


# ── обработка джобы (D2 state machine) ──────────────────────────────────────

async def run_job(memory, index_name: str, job_id: str) -> None:
    """Полный rebuild одного индекса: батчи → checkpoint → validate → activate.

    НЕ бросает (background fire-and-forget); любой сбой → `failed` с
    reason_code, FTS остаётся serviceable, автоматического retry-storm нет
    (повтор — по следующему startup-schedule / явному триггеру)."""
    db = memory.db
    spec = _INDEX_SPECS[index_name]
    try:
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
    except Exception:
        store = None

    row = await _get_job(db, job_id)
    if row is None:
        return
    try:
        payload = json.loads(row["payload"] or "{}")
    except ValueError:
        payload = {}
    fp = str(payload.get("fingerprint") or "")
    generation = int(payload.get("generation") or 0)
    # `save_checkpoint` (v14) перезаписывает `payload` checkpoint-обёрткой —
    # identity build'а на resume восстанавливаем из coalesce_key
    # (`graphrag_rebuild:{index}:{fp}`) + реестра поколений.
    if (not fp or generation <= 0) and index_name in _INDEX_SPECS:
        parts = str(row.get("coalesce_key") or "").split(":", 2)
        if len(parts) == 3 and parts[0] == _KIND and parts[1] == index_name:
            fp = fp or parts[2]
            if generation <= 0 and fp:
                gen_row = await db.get_generation_by_fingerprint(
                    index_name, fp)
                generation = int((gen_row or {}).get("generation") or 0)
    if not fp or generation <= 0:
        await _job_cas(db, job_id, expect=str(row["status"]),
                       set_status=ST_FAILED, reason_code="bad_payload",
                       terminal=True)
        return

    # resume из checkpoint (restart mid-build → продолжение, §7/§70)
    last_id = 0
    processed = 0
    if store is not None:
        checkpoint = await store.get_checkpoint(job_id)
        if checkpoint and checkpoint.get("cursor"):
            try:
                cur = json.loads(str(checkpoint["cursor"]))
                last_id = int(cur.get("last_id", 0))
                processed = int(cur.get("processed", 0))
            except (ValueError, TypeError):
                last_id, processed = 0, 0

    prior_status = str(row["status"] or ST_QUEUED)
    if prior_status in (ST_ACTIVATED, ST_CANCELLED, ST_PAUSED):
        return
    # ASAP-4 §68 (restart during pause): job читает next_allowed_at, не
    # сбрасывает generation, не дублирует работу — resume той же generation
    # после истечения cooldown.
    if prior_status in AUTO_RESUME_STATUSES:
        gen_row = await db.get_generation_by_fingerprint(index_name, fp)
        next_allowed = int((gen_row or {}).get("next_allowed_at") or 0)
        if await _horizon_exhausted(db, job_id):
            # §25: bounded retry horizon исчерпан → terminal FAILED.
            await _job_cas(db, job_id, expect=prior_status,
                           set_status=ST_FAILED,
                           reason_code="retry_horizon_exhausted",
                           terminal=True)
            _emit("EMBEDDING_GENERATION_FAILED", "failed", level="error",
                  index=index_name, generation=generation,
                  reason_code="retry_horizon_exhausted")
            return
        if next_allowed and int(time.time()) < next_allowed:
            _schedule_auto_resume(memory, db, index_name,
                                  next_allowed - int(time.time()))
            return
        await _registry_resume(db, index_name, fp)
    # Конвертация существующего terminal-failed quota-класса (деплой AM-1):
    # честный terminal от ADR-1028-5 → paused/resumable. Бит-в-бит legacy
    # остаётся при EMBED_CONTROL_PLANE_ENABLED=false — там ветка не выполняется.
    if prior_status == ST_FAILED and _control_plane_on():
        reason = str(row["reason_code"] or "")
        # reason_code хранит имя класса исключения (LLMRateLimitError) —
        # проверяем строку напрямую, не оборачивая в RuntimeError.
        if ("RateLimit" in reason or "429" in reason
                or reason.startswith("rate_limit")):
            await _job_cas(db, job_id, expect=ST_FAILED,
                           set_status=ST_PAUSED_RATE_LIMIT,
                           reason_code="rebuild_quota_conversion")
            next_allowed = int(time.time()) + _default_cooldown_s()
            await _pause_bookkeeping(db, job_id, "rate_limit_conversion",
                                     next_allowed)
            await _registry_pause(db, index_name, fp,
                                  "rate_limit_conversion", next_allowed)
            _schedule_auto_resume(memory, db, index_name,
                                  _default_cooldown_s())
            return
    if not await _job_cas(db, job_id, expect=prior_status,
                          set_status=ST_RUNNING):
        return

    # ── ASAP-4 (T-4407, §22/§23): shared full-rebuild permit на deployment ──
    # ≤1 active full-rebuild (graph_facts_vec и smart_archive не открывают
    # quota-race; прод-факт Q6). Lease через существующую task_jobs (REUSE,
    # Redis запрещён); process-local semaphores недостаточны.
    lease = None
    priority_token = None
    if _control_plane_on():
        try:
            from services.embedding_control_plane import RebuildLease
            lease = RebuildLease(db)
            if not await lease.acquire(index_name):
                await _job_cas(db, job_id, expect=ST_RUNNING,
                               set_status=ST_QUEUED,
                               reason_code="rebuild_lease_waiting")
                try:
                    from services.mca_events import emit_mca_event
                    emit_mca_event(
                        "EMBEDDING_GENERATION_BUILD_START", outcome="skipped",
                        level="info", component="graphrag_rebuild",
                        index=index_name, generation=generation,
                        reason_code="rebuild_lease_waiting")
                except Exception:
                    pass
                logger.info(
                    "graphrag rebuild: lease busy — queued | index=%s | "
                    "gen=%d", index_name, generation)
                return
        except Exception:
            logger.warning("graphrag rebuild: lease acquire failed — "
                           "продолжаем без permit (fail-open)", exc_info=True)
            lease = None

    shadow = _shadow_name(index_name, generation)
    _emit("EMBEDDING_GENERATION_BUILD_START", "start",
          index=index_name, generation=generation,
          job_id=str(job_id)[:64], fp=_fp12(fp),
          resumed=bool(processed))
    logger.info("EMBEDDING_GENERATION_BUILD_START | index=%s | gen=%d | "
                "fp=%s | resumed=%s | job=%s", index_name, generation,
                _fp12(fp), bool(processed), str(job_id)[:16])

    try:
        await _create_shadow(memory, index_name, shadow)
        # §28/Q10: pre-check source coverage ДО embed-стадии — пустой source
        # не должен проходить полный «build из нуля объектов» и падать на
        # smoke; честный distinct reason сразу. OFF-паритет: прежний путь.
        if _control_plane_on():
            cursor = await db.db.execute(
                f"SELECT COUNT(*) AS c FROM {spec['source']}")
            if int((await cursor.fetchone())["c"]) == 0:
                await _job_cas(db, job_id, expect=ST_RUNNING,
                               set_status=ST_VALIDATION_FAILED,
                               reason_code="knn_source_empty")
                _emit("EMBEDDING_GENERATION_FAILED", "failed", level="info",
                      index=index_name, generation=generation,
                      reason_code="knn_source_empty",
                      report=json.dumps({"source_count": 0},
                                        ensure_ascii=False)[:256])
                logger.info("EMBEDDING_GENERATION_FAILED | index=%s | gen=%d | "
                            "reason=knn_source_empty (source empty)",
                            index_name, generation)
                return
        batch_no = 0
        last_progress_emit = 0.0
        # D2 (T-4503): первый успешный батч после resume обнуляет
        # quota_exhaust_streak (одна точка; пишется только если стрик был).
        streak_cleared = False
        # ASAP-4 (T-4406): приоритет P3 на весь цикл батчей — через контекст
        # контрол-плейна (НЕ kwarg `_embed`: контракт memory._embed не
        # расширяется для моков/потребителей).
        priority_token = None
        try:
            from services.embedding_control_plane import (set_priority,
                                                          reset_priority)
            priority_token = set_priority(_rebuild_priority())
        except Exception:      # pragma: no cover
            priority_token = None
        while True:
            current = await _get_job(db, job_id)
            status = str((current or {}).get("status") or "")
            if status in (ST_PAUSED, ST_PAUSED_RATE_LIMIT,
                          ST_PAUSED_PROVIDER):
                return                      # §64/AM-1: resume — отдельным путём
            if status == ST_CANCELLED:
                await _drop_shadow(memory, shadow)
                return
            if status != ST_RUNNING:
                return
            batch = await _fetch_batch(memory, spec, last_id)
            if not batch:
                break
            try:
                vectors = await memory._embed([b["fact"] for b in batch])
            except Exception as exc:
                if _control_plane_on():
                    # AM-1 (T-4408): 429/provider-quota → paused_*, НЕ
                    # terminal failed; auth → terminal (§25).
                    await _handle_build_failure(memory, db, index_name,
                                                job_id, fp, generation, exc)
                else:
                    # OFF-паритет: прежний «честный terminal» (ADR-1028-5 D2).
                    reason = type(exc).__name__[:60]
                    await _job_cas(db, job_id, expect=ST_RUNNING,
                                   set_status=ST_FAILED, reason_code=reason,
                                   terminal=True)
                    _emit("EMBEDDING_GENERATION_FAILED", "failed",
                          level="error", index=index_name,
                          generation=generation, reason_code=reason)
                    logger.error("EMBEDDING_GENERATION_FAILED | index=%s | "
                                 "gen=%d | error=%s", index_name, generation,
                                 reason, exc_info=True)
                return
            await _insert_shadow_rows(memory, spec, shadow, batch, vectors)
            last_id = int(batch[-1]["id"])
            processed += len(batch)
            batch_no += 1
            if store is not None:
                await store.save_checkpoint(
                    job_id,
                    cursor_token=json.dumps({"last_id": last_id,
                                             "processed": processed}),
                    processed=processed,
                    checkpoint_ref=f"cp:{index_name}:{generation}")
                await store.heartbeat(job_id)
            if not streak_cleared:
                streak_cleared = True
                await _clear_quota_streak(db, job_id)
            if lease is not None:
                try:
                    await lease.heartbeat()
                except Exception:
                    pass
            now_mono = time.monotonic()
            if batch_no % 20 == 0 or now_mono - last_progress_emit >= 30.0:
                last_progress_emit = now_mono
                _emit("EMBEDDING_GENERATION_PROGRESS", "progress",
                      index=index_name, generation=generation,
                      processed=int(processed), frontier=int(last_id),
                      job_id=str(job_id)[:64])
                logger.info("EMBEDDING_GENERATION_PROGRESS | index=%s | "
                            "gen=%d | processed=%d | frontier=%d",
                            index_name, generation, processed, last_id)
            sleep_s = _sleep_seconds()
            if sleep_s > 0:
                await asyncio.sleep(sleep_s)   # §64: yield между батчами

        # build-фаза завершена, checkpoint durable → валидация.
        if not await _job_cas(db, job_id, expect=ST_RUNNING,
                              set_status=ST_CHECKPOINT):
            return
        ok, report = await _validate(memory, index_name, shadow, fp, last_id)
        if not ok:
            reason = str(report.get("reason_code") or "validation_failed")
            # T-4409 (§29): validation_failure ≠ data loss — НО только для
            # KNN-класса (недоказанный smoke): vectors сохраняются для
            # диагностики/repair. Структурные фейлы (fingerprint_changed /
            # missing_vectors / identity_changed — D2 race-guard и
            # доказанная invalid data, §25) остаются terminal «как раньше»
            # в ОБОИХ режимах: механика D2 не меняется (ADR-1028-7 AM-1).
            if _control_plane_on() and reason.startswith("knn_"):
                await _job_cas(db, job_id, expect=ST_CHECKPOINT,
                               set_status=ST_VALIDATION_FAILED,
                               reason_code=reason)
                _emit("EMBEDDING_GENERATION_FAILED", "failed", level="warning",
                      index=index_name, generation=generation,
                      reason_code=reason, report=json.dumps(
                          {k: v for k, v in report.items() if k != "criteria"},
                          ensure_ascii=False)[:512])
                logger.warning(
                    "EMBEDDING_GENERATION_VALIDATION_FAILED | index=%s | "
                    "gen=%d | reason=%s | vectors preserved",
                    index_name, generation, reason)
                return
            await _job_cas(db, job_id, expect=ST_CHECKPOINT,
                           set_status=ST_FAILED, reason_code=reason,
                           terminal=True)
            await _drop_shadow(memory, shadow)
            # Retry после validation-failure обязан начать полный rebuild
            # заново (cursor за missing-row дал бы вечный повтор failure):
            # checkpoint сбрасывается, shadow удалён выше.
            if store is not None:
                try:
                    await store.save_checkpoint(
                        job_id,
                        cursor_token=json.dumps({"last_id": 0,
                                                 "processed": 0}),
                        processed=0,
                        checkpoint_ref=f"cp:{index_name}:{generation}:reset")
                except Exception:
                    pass
            _emit("EMBEDDING_GENERATION_FAILED", "failed", level="warning",
                  index=index_name, generation=generation,
                  reason_code=reason, report=json.dumps(
                      {k: v for k, v in report.items() if k != "criteria"},
                      ensure_ascii=False)[:512])
            logger.warning("EMBEDDING_GENERATION_FAILED | index=%s | gen=%d | "
                           "reason=%s", index_name, generation, reason)
            if reason == "fingerprint_changed":
                # §70: config changes during build → старый build НЕ
                # активируется как current; новый queued build под новый fp.
                try:
                    from services.summary_memory import fire_and_forget
                    fire_and_forget(maybe_schedule_rebuilds(memory),
                                    "graphrag_rebuild")
                except Exception:
                    logger.warning("graphrag rebuild: re-schedule failed",
                                   exc_info=True)
            return

        if not await _job_cas(db, job_id, expect=ST_CHECKPOINT,
                              set_status=ST_VALIDATED):
            return
        crit = report.get("criteria") or {}
        _emit("EMBEDDING_GENERATION_VALIDATED", "success",
              index=index_name, generation=generation,
              processed=int(processed),
              eligible=int(report.get("eligible_total") or 0),
              criteria=json.dumps(crit, ensure_ascii=False)[:400])
        logger.info("EMBEDDING_GENERATION_VALIDATED | index=%s | gen=%d | "
                    "eligible=%d | criteria=%s", index_name, generation,
                    report.get("eligible_total"),
                    ",".join(k for k, v in crit.items() if v))

        if not await _activate(memory, index_name, shadow, fp, generation):
            await _job_cas(db, job_id, expect=ST_VALIDATED,
                           set_status=ST_FAILED,
                           reason_code="activation_failed", terminal=True)
            _emit("EMBEDDING_GENERATION_FAILED", "failed", level="error",
                  index=index_name, generation=generation,
                  reason_code="activation_failed")
            return
        await _job_cas(db, job_id, expect=ST_VALIDATED,
                       set_status=ST_ACTIVATED, terminal=True)
        _emit("EMBEDDING_GENERATION_ACTIVATED", "success",
              index=index_name, generation=generation, fp=_fp12(fp),
              vectors=int(report.get("covered") or 0))
        logger.info("EMBEDDING_GENERATION_ACTIVATED | index=%s | gen=%d | "
                    "vectors=%d — vector path active, FTS fallback "
                    "available", index_name, generation,
                    report.get("covered"))
    except Exception as exc:
        if _control_plane_on():
            # AM-1/§25: escape-ошибки (вне embed-вызова) проходят ту же
            # классификацию; deterministic DB/schema-класс остаётся terminal.
            await _handle_build_failure(memory, db, index_name, job_id,
                                        fp, generation, exc)
            return
        reason = type(exc).__name__[:60]
        await _job_cas(db, job_id, expect=ST_RUNNING, set_status=ST_FAILED,
                       reason_code=reason, terminal=True)
        _emit("EMBEDDING_GENERATION_FAILED", "failed", level="error",
              index=index_name, generation=generation, reason_code=reason)
        logger.error("EMBEDDING_GENERATION_FAILED | index=%s | gen=%d | "
                     "error=%s", index_name, generation, reason,
                     exc_info=True)
    finally:
        # ASAP-4: контекст приоритета P3 закрывается на всех путях.
        if priority_token is not None:
            try:
                from services.embedding_control_plane import reset_priority
                reset_priority(priority_token)
            except Exception:      # pragma: no cover
                pass
        # T-4407: permit освобождается на ВСЕХ путях → ожидающий index
        # стартует следующим («сначала меньший/застрявший, затем второй»).
        if lease is not None:
            try:
                await lease.release()
            except Exception:
                pass
        if _control_plane_on():
            try:
                await maybe_schedule_rebuilds(memory, include_failed=False)
            except Exception:
                logger.warning("graphrag rebuild: post-release schedule "
                               "failed", exc_info=True)


async def _apply_pause(memory, db, index_name: str, job_id: str, fp: str,
                       generation: int, *, expect: str, new_status: str,
                       reason_code: str, next_allowed: int, delay: float,
                       exc_name: str | None = None,
                       quota_streak: int | None = None,
                       quota_kind: str | None = None) -> None:
    """Общая «пауза» AM-1: CAS (от фактического статуса) + pause-метаданные
    в result_ref + pause-колонки реестра (v23) + событие + авто-resume.
    Checkpoint НЕ трогается (resume продолжит с него)."""
    await _job_cas(db, job_id, expect=expect, set_status=new_status,
                   reason_code=reason_code)
    await _pause_bookkeeping(db, job_id, reason_code, next_allowed,
                             quota_streak=quota_streak,
                             quota_kind=quota_kind)
    await _registry_pause(db, index_name, fp, reason_code, next_allowed)
    reason_ui = ("paused_rate_limit"
                 if new_status == ST_PAUSED_RATE_LIMIT else "paused_provider")
    _emit("EMBEDDING_GENERATION_PAUSED", "silent", level="info",
          index=index_name, generation=generation, reason_code=reason_ui,
          next_allowed_at=next_allowed)
    detail = f" | exc={exc_name}" if exc_name else ""
    logger.warning(
        "EMBEDDING_GENERATION_PAUSED | index=%s | gen=%d | reason=%s | "
        "kind=%s%s | cooldown_s=%.1f | checkpoint preserved",
        index_name, generation, reason_ui, reason_code, detail, delay)
    _schedule_auto_resume(memory, db, index_name, delay)


async def _handle_build_failure(memory, db, index_name: str, job_id: str,
                                fp: str, generation: int,
                                exc: Exception) -> None:
    """Классификация сбоя build'а (AM-1 + §25):
    * horizon исчерпан → terminal `failed` (bounded, §25);
    * auth (401/403) → terminal `failed` (auth_invalid);
    * control-plane quota (`EmbeddingGroupCoolingDown` — группа ушла в
      cooldown между батчами) → `paused_rate_limit` с next_allowed_at из
      исключения (H-ASAP4-2: НЕ terminal);
    * control-plane budget/busy (`EmbeddingBudgetExhausted` /
      `EmbeddingConcurrencyBusy`) → `paused_provider` (авто-resume; horizon
      ограничивает);
    * 429/quota (LLM-класс) → `paused_rate_limit` (registry + bookkeeping);
    * provider 5xx/timeout/transport → `paused_provider` (авто-resume);
    * остальное (deterministic schema/DB) → terminal `failed` (как раньше).
    CAS выполняется от ФАКТИЧЕСКОГО статуса джобы (M-ASAP4-3): исключение на
    пост-checkpoint стадии больше не теряется молча — deterministic-класс
    получает честный terminal, quota-класс — паузу с checkpoint-preserved.
    FTS serviceable во всех состояниях; checkpoint НЕ трогается.
    """
    # M-ASAP4-3: фактический статус → корректный expect для всех CAS ниже.
    try:
        current = await _get_job(db, job_id)
        current_status = str((current or {}).get("status") or ST_RUNNING)
    except Exception:      # pragma: no cover — чтение статуса не роняет классификацию
        current_status = ST_RUNNING
    expect = (current_status if current_status in _FAILURE_CAS_FROM
              else ST_RUNNING)
    if await _horizon_exhausted(db, job_id):
        await _job_cas(db, job_id, expect=expect, set_status=ST_FAILED,
                       reason_code="retry_horizon_exhausted", terminal=True)
        _emit("EMBEDDING_GENERATION_FAILED", "failed", level="error",
              index=index_name, generation=generation,
              reason_code="retry_horizon_exhausted")
        logger.error("EMBEDDING_GENERATION_FAILED | index=%s | gen=%d | "
                     "reason=retry_horizon_exhausted", index_name, generation)
        return
    if _is_auth_exception(exc):
        # §25: auth/config invalid — terminal; ретраить как 429 нельзя.
        await _job_cas(db, job_id, expect=expect, set_status=ST_FAILED,
                       reason_code="auth_invalid", terminal=True)
        _emit("EMBEDDING_GENERATION_FAILED", "failed", level="error",
              index=index_name, generation=generation,
              reason_code="auth_invalid")
        logger.error("EMBEDDING_GENERATION_FAILED | index=%s | gen=%d | "
                     "reason=auth_invalid (%s)", index_name, generation,
                     type(exc).__name__)
        return
    # H-ASAP4-2: control-plane классы — ДО эвристик по именам (их имена не
    # матчатся ни на один legacy-класс и раньше уезжали в terminal failed).
    try:
        from services.embedding_control_plane import EmbeddingGroupCoolingDown
        is_cooling = isinstance(exc, EmbeddingGroupCoolingDown)
    except Exception:      # pragma: no cover — контракт контрол-плейна есть всегда
        is_cooling = False
    if is_cooling:
        # Группа уже в cooldown (executor считал next_allowed_at) — повторная
        # классификация тела не нужна: честный Retry-After из исключения.
        # D4 (T-4503): record_rate_limit здесь НЕ дублируется — реальный 429
        # уже посчитан в `_on_error` контрол-плейна (точка истины); двойной
        # инкремент завышал `429_last_10m` ×2 (RCA §3).
        exc_next = int(getattr(exc, "next_allowed_at", 0) or 0)
        now = int(time.time())
        # D2: стрик подряд exhausted-пауз (result_ref, рестарт-персистентный).
        streak = await _quota_streak(db, job_id)
        if exc_next > now:
            # Parking/RA-горизонт: resume строго на next_allowed_at — backoff
            # поверх честного reset не наслаивается (D2).
            delay = float(exc_next - now)
            next_allowed = exc_next
        else:
            # Пауза БЕЗ parking-горизонта → нелинейный backoff (D2).
            if _resume_backoff_enabled():
                delay = _resume_backoff_delay(streak)
            else:
                delay = _default_cooldown_s()
            next_allowed = int(now + delay)
        await _apply_pause(memory, db, index_name, job_id, fp, generation,
                           expect=expect, new_status=ST_PAUSED_RATE_LIMIT,
                           reason_code="rate_limit:quota_group",
                           next_allowed=next_allowed, delay=delay,
                           quota_streak=streak + 1,
                           quota_kind=_quota_kind_of_pause(
                               "rate_limit:quota_group", exc))
        return
    try:
        from services.embedding_control_plane import (
            EmbeddingBudgetExhausted, EmbeddingConcurrencyBusy)
        is_busy = isinstance(exc, (EmbeddingBudgetExhausted,
                                   EmbeddingConcurrencyBusy))
    except Exception:      # pragma: no cover
        is_busy = False
    if is_busy:
        # Budget исчерпан (transport ≤4) / scheduler busy: provider-сигнала
        # нет — developer-кулдаун ×2 в пределах safety ceiling; horizon §25
        # ограничивает суммарное время пауз.
        try:
            from config.settings import settings
            ceiling = float(getattr(settings,
                                    "EMBED_RETRY_AFTER_CEILING_SECONDS",
                                    300.0))
        except Exception:      # pragma: no cover
            ceiling = 300.0
        delay = min(_default_cooldown_s() * 2.0, ceiling)
        await _apply_pause(memory, db, index_name, job_id, fp, generation,
                           expect=expect, new_status=ST_PAUSED_PROVIDER,
                           reason_code="provider_unavailable",
                           next_allowed=int(time.time() + delay), delay=delay,
                           exc_name=type(exc).__name__)
        return
    if _is_rate_limit_exception(exc):
        # Легаси/обходной путь (исключение НЕ через executor — _on_error не
        # выполнялся): инкремент 429 здесь единственный (D4-дедуп касается
        # только CoolingDown-конверсии).
        has_provider_ra = False
        rate_kind = "unknown"
        spend_kinds = ("spend", "daily_project")
        try:
            from services.embedding_control_plane import (
                REGISTRY as ECP_REGISTRY, classify_rate_limit,
                retry_after_seconds, RateLimitInfo, RATE_SPEND, RATE_DAILY)
            spend_kinds = (RATE_SPEND, RATE_DAILY)
            headers = getattr(exc, "headers", None)
            body = getattr(exc, "body", None)
            info = classify_rate_limit(
                429, headers, body if isinstance(body, str) else None)
            delay = retry_after_seconds(info)
            rate_kind = str(info.kind)
            has_provider_ra = info.retry_after_s is not None
            ECP_REGISTRY.record_rate_limit()
        except Exception:
            info = RateLimitInfo(kind="unknown", retry_after_s=None)
            delay = _default_cooldown_s()
        # D2: нелинейный backoff — только для пауз БЕЗ provider-горизонта
        # (kind unknown/tpm без RA); RA/parking-горизонт не умножается.
        if (_resume_backoff_enabled() and not has_provider_ra
                and rate_kind not in spend_kinds):
            delay = _resume_backoff_delay(await _quota_streak(db, job_id))
        await _apply_pause(memory, db, index_name, job_id, fp, generation,
                           expect=expect, new_status=ST_PAUSED_RATE_LIMIT,
                           reason_code=f"rate_limit:{info.kind}",
                           next_allowed=int(time.time() + delay), delay=delay,
                           quota_kind=_quota_kind_of_pause(
                               f"rate_limit:{info.kind}"))
        return
    if _is_provider_unavailable(exc):
        # paused_provider: экспоненциальный (×2 от дефолта) кулдаун в
        # пределах safety ceiling; provider-сигнала нет — developer bound.
        try:
            from config.settings import settings
            ceiling = float(getattr(settings,
                                    "EMBED_RETRY_AFTER_CEILING_SECONDS",
                                    300.0))
        except Exception:      # pragma: no cover
            ceiling = 300.0
        delay = min(_default_cooldown_s() * 2.0, ceiling)
        await _apply_pause(memory, db, index_name, job_id, fp, generation,
                           expect=expect, new_status=ST_PAUSED_PROVIDER,
                           reason_code="provider_unavailable",
                           next_allowed=int(time.time() + delay), delay=delay,
                           exc_name=type(exc).__name__)
        return
    # Deterministic schema/DB error и прочее — прежний honest terminal (§25).
    reason = type(exc).__name__[:60]
    await _job_cas(db, job_id, expect=expect, set_status=ST_FAILED,
                   reason_code=reason, terminal=True)
    _emit("EMBEDDING_GENERATION_FAILED", "failed", level="error",
          index=index_name, generation=generation, reason_code=reason)
    logger.error("EMBEDDING_GENERATION_FAILED | index=%s | gen=%d | "
                 "error=%s", index_name, generation, reason,
                 exc_info=True)


# ── планировщик (startup / перетриггер) ─────────────────────────────────────

async def maybe_schedule_rebuilds(memory, *, include_failed: bool = True
                                  ) -> list[str]:
    """Для каждого индекса: latest generation `building` с fingerprint ==
    current → гарантировать durable-джобу и запустить (resume) её.

    ASAP-4 (T-4407, §23): full-rebuild'ы не стартуют одновременно — общий
    permit (`RebuildLease`, task_jobs) + последовательность «сначала
    меньший/застрявший, затем второй»: застрявший (есть checkpoint-прогресс)
    идёт первым, иначе индекс с меньшим source-остатком. Второй индекс
    стартует после освобождения permit (post-release schedule в run_job).

    `include_failed=False` (post-release вызов): failed/validation_failed
    джобы НЕ переоткрываются — ретрай failure-класса остаётся bounded
    (startup-schedule/явный триггер), иначе post-release превращается в
    retry-storm (анти-паттерн §6).

    Возвращает список запущенных/возобновлённых индексов (для лога/тестов).
    Никогда не бросает."""
    if not graphrag_rebuild_enabled():
        return []
    scheduled: list[str] = []
    try:
        db = memory.db
        if not hasattr(db, "get_latest_embedding_generation"):
            return []
        current_fp = memory._identity_fingerprint()
        candidates: list[tuple[str, str, int]] = []   # (index, job_id, prio)
        for index_name in _INDEX_SPECS:
            try:
                gen = await db.get_latest_embedding_generation(index_name)
            except Exception:
                continue
            if gen is None or str(gen.get("status") or "") != "building":
                # active → всё обслуживается; failed/superseded — не наш случай
                continue
            fp = str(gen.get("fingerprint") or "")
            if not fp or fp != current_fp:
                continue          # mismatch — старый build не оживляем (D2)
            generation = int(gen.get("generation") or 0)
            if generation <= 0:
                continue
            current_job = await _find_active_job(db, index_name, fp)
            if current_job is not None and not include_failed:
                status = str(current_job.get("status") or "")
                if status in (ST_FAILED, ST_VALIDATION_FAILED):
                    continue      # bounded retry — не из post-release
            job = await _ensure_job(db, index_name, fp, generation)
            if job is None:
                continue
            # §23: «сначала меньший/застрявший» — застрявший (прогресс > 0)
            # приоритетнее; иначе меньше оставшихся фактов.
            progress = await _job_progress(db, job)
            remaining = await _source_remaining(db, index_name, fp)
            priority = (0, -progress, remaining)
            candidates.append((index_name, job, priority[0] * 10**12
                               + priority[1] * 10**6 + min(priority[2], 10**6 - 1)))
        candidates.sort(key=lambda item: item[2])
        for index_name, job, _prio in candidates[:1]:
            scheduled.append(index_name)
            try:
                from services.summary_memory import fire_and_forget
                fire_and_forget(run_job(memory, index_name, job),
                                f"graphrag_rebuild:{index_name}")
            except Exception:
                logger.warning("graphrag rebuild: fire failed | index=%s",
                               index_name, exc_info=True)
        # Остальные кандидаты остаются queued — их подберёт post-release
        # schedule первого (lease-последовательность §23).
    except Exception:
        logger.warning("graphrag rebuild: schedule failed", exc_info=True)
    return scheduled


async def _job_progress(db, job_id: str) -> int:
    """Processed из checkpoint'а (0 — застрявших нет)."""
    try:
        from services.task_supervisor import TaskJobStore
        checkpoint = await TaskJobStore(db).get_checkpoint(job_id)
        if checkpoint and checkpoint.get("cursor"):
            cur = json.loads(str(checkpoint["cursor"]))
            return int(cur.get("processed", 0))
    except Exception:
        return 0
    return 0


async def _source_remaining(db, index_name: str, fp: str) -> int:
    """Оценка remaining (eligible source ещё без векторов в shadow)."""
    try:
        spec = _INDEX_SPECS[index_name]
        gen = await db.get_generation_by_fingerprint(index_name, fp)
        generation = int((gen or {}).get("generation") or 0)
        shadow = _shadow_name(index_name, generation) if generation else None
        now = int(time.time())
        if spec["eligible_ts"]:
            sql = (f"SELECT COUNT(*) AS c FROM {spec['source']} "
                   "WHERE (expires_at IS NULL OR expires_at > ?)")
            params: list = [now]
        else:
            sql = f"SELECT COUNT(*) AS c FROM {spec['source']}"
            params = []
        if shadow:
            sql += f" AND id NOT IN (SELECT fact_id FROM {shadow})"
        cursor = await db.db.execute(sql, tuple(params))
        return int((await cursor.fetchone())["c"])
    except Exception:
        return 10**9      # неизвестно → самый низкий приоритет оценки


def ticker_active() -> bool:
    """D10/T-5255: запущен ли в этом процессе periodic future-resume тик."""
    return _resume_ticker_started


async def _source_empty(db, index_name: str) -> bool:
    """D10/T-5255: источник rebuild'а пуст (eligible-строк 0)? Fail-open:
    ошибка чтения → False (не «пусто») — reopen остаётся возможен, честный
    reason `knn_source_empty` джоба вернёт сама при следующем прогоне."""
    try:
        spec = _INDEX_SPECS[index_name]
        now = int(time.time())
        if spec["eligible_ts"]:
            sql = (f"SELECT COUNT(*) AS c FROM {spec['source']} "
                   "WHERE (expires_at IS NULL OR expires_at > ?)")
            cursor = await db.db.execute(sql, (now,))
        else:
            cursor = await db.db.execute(
                f"SELECT COUNT(*) AS c FROM {spec['source']}")
        row = await cursor.fetchone()
        return row is None or int(row["c"]) == 0
    except Exception:
        return False


async def _source_total(db, index_name: str) -> int:
    """D10/T-5255: всего eligible-строк источника (знаменатель «N/M»).
    Fail-open: ошибка → 0 (панель покажет M=0, не выдумывает число)."""
    try:
        spec = _INDEX_SPECS[index_name]
        now = int(time.time())
        if spec["eligible_ts"]:
            sql = (f"SELECT COUNT(*) AS c FROM {spec['source']} "
                   "WHERE (expires_at IS NULL OR expires_at > ?)")
            cursor = await db.db.execute(sql, (now,))
        else:
            cursor = await db.db.execute(
                f"SELECT COUNT(*) AS c FROM {spec['source']}")
        row = await cursor.fetchone()
        return int(row["c"]) if row is not None else 0
    except Exception:
        return 0


async def _ensure_job(db, index_name: str, fp: str, generation: int
                      ) -> str | None:
    """Найти/создать durable-джобу rebuild'а (coalesce по index+fp).

    ASAP-4 (AM-1/§68): `paused_rate_limit`/`paused_provider` — авто-resume
    ПОСЛЕ `next_allowed_at` (реестр поколений, v23-колонки); операторская
    `paused` — не авто; `validation_failed` — переоткрытие по schedule
    (bounded, как `failed`); `failed` quota-класса конвертируется run_job'ом
    в paused/resumable (control-plane ON)."""
    job = await _find_active_job(db, index_name, fp)
    if job is not None:
        status = str(job.get("status") or "")
        jid = str(job["job_id"])
        if status in (ST_RUNNING, ST_BUILDING):
            heartbeat = int(job.get("heartbeat_at") or 0)
            if int(time.time()) - heartbeat < _STALE_RUNNING_SECONDS:
                return None             # уже выполняется в живом процессе
            # stale running (процесс умер) → переоткрыть как queued (resume).
            await _job_cas(db, jid, expect=status, set_status=ST_QUEUED,
                           reason_code="stale_takeover")
            return jid
        if status == ST_PAUSED:
            return None                 # явная пауза — не авто-возобновляем
        if status in AUTO_RESUME_STATUSES:
            # §68: restart during pause — читаем next_allowed_at из реестра;
            # не истёк → ждём (generation НЕ сбрасывается). D10/T-5255: ожидание
            # в окне cooldown — норма (no-op тика); resume приходит следующим
            # тиком `start_resume_ticker` ПОСЛЕ истечения next_allowed_at,
            # в т.ч. в новом процессе после рестарта.
            gen = await db.get_generation_by_fingerprint(index_name, fp)
            next_allowed = int((gen or {}).get("next_allowed_at") or 0)
            if next_allowed and int(time.time()) < next_allowed:
                return None
            await _job_cas(db, jid, expect=status, set_status=ST_QUEUED,
                           reason_code="cooldown_expired")
            await _registry_resume(db, index_name, fp)
            return jid
        if status in (ST_QUEUED, ST_CHECKPOINT, ST_VALIDATION_FAILED,
                      "interrupted"):
            if status == ST_VALIDATION_FAILED:
                # D10/T-5255 (RCA §2.4): `knn_source_empty` при ПУСТОМ
                # источнике — stable terminal с видимой причиной (vectors
                # сохранены, T-4409): по schedule не переоткрываем, иначе
                # вечный startup-цикл BUILD_START→FAILED на каждом рестарте.
                # Появились строки в источнике → reopen снова разрешён.
                if str(job.get("reason_code") or "") == "knn_source_empty" \
                        and await _source_empty(db, index_name):
                    return None
            if status == "interrupted":
                await _job_cas(db, jid, expect="interrupted",
                               set_status=ST_QUEUED,
                               reason_code="restart_resume")
            return jid
        if status in (ST_ACTIVATED, ST_CANCELLED):
            return None
        if status == ST_FAILED:
            # D2: повторный build после failure — bounded (один раз на
            # startup-schedule), НЕ storm: переоткрываем существующую джобу.
            # AM-1: quota-класс (LLMRateLimitError) конвертируется run_job'ом
            # в paused/resumable, не в лобовой повтор.
            await _job_cas(db, jid, expect=ST_FAILED, set_status=ST_QUEUED,
                           reason_code="retry_on_schedule")
            return jid
        return None
    try:
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
        return await store.enqueue(
            owner=_OWNER, kind=_KIND,
            coalesce_key=_coalesce_key(index_name, fp),
            payload=json.dumps({"index": index_name, "fingerprint": fp,
                                "generation": generation},
                               ensure_ascii=False))
    except Exception:
        logger.warning("graphrag rebuild: enqueue failed | index=%s",
                       index_name, exc_info=True)
        return None


# ── §64: pause/resume/cancel + статус (для health/Analytics T-4216) ─────────

async def pause_rebuild(db, index_name: str) -> bool:
    job = await _find_active_job(db, index_name,
                                 await _current_fp_async(db, index_name) or "")
    if job is None:
        return False
    return await _job_cas(db, str(job["job_id"]), expect=ST_RUNNING,
                          set_status=ST_PAUSED, reason_code="paused")


async def resume_rebuild(db, index_name: str, *, fp: str | None = None
                         ) -> bool:
    """Операторский resume: `paused` ИЛИ quota/provider-пауза → queued
    (ASAP-4: авто-resume и так покрывает paused_rate_limit/provider, но
    явная команда должна работать для всех pause-статусов)."""
    fp = fp or (await _current_fp_async(db, index_name) or "")
    job = await _find_active_job(db, index_name, fp)
    if job is None:
        return False
    status = str(job.get("status") or "")
    if status not in (ST_PAUSED,) | AUTO_RESUME_STATUSES:
        return False
    ok = await _job_cas(db, str(job["job_id"]), expect=status,
                        set_status=ST_QUEUED, reason_code="resumed")
    if ok:
        await _registry_resume(db, index_name, fp)
    return ok


async def cancel_rebuild(db, index_name: str, *, fp: str | None = None
                         ) -> bool:
    fp = fp or (await _current_fp_async(db, index_name) or "")
    job = await _find_active_job(db, index_name, fp)
    if job is None:
        return False
    status = str(job.get("status") or "")
    if status in (ST_ACTIVATED, ST_CANCELLED, ST_FAILED):
        return False
    return await _job_cas(db, str(job["job_id"]), expect=status,
                          set_status=ST_CANCELLED, reason_code="cancelled",
                          terminal=True)


async def _current_fp_async(db, index_name: str) -> str | None:
    """Async-источник fingerprint активного building-поколения (реестр)."""
    try:
        gen = await db.get_latest_embedding_generation(index_name)
        if gen is not None and str(gen.get("status") or "") == "building":
            return str(gen.get("fingerprint") or "")
    except Exception:      # pragma: no cover
        logger.warning("graphrag rebuild: current fp read failed", exc_info=True)
    return None


async def rebuild_status(db) -> dict:
    """Снимок rebuild-состояния (R17-safe; для GraphRAG health T-4216)."""
    out: dict = {}
    try:
        cursor = await db.db.execute(
            "SELECT job_id, coalesce_key, status, reason_code, payload, "
            "progress_at, heartbeat_at, created_at, updated_at FROM task_jobs "
            "WHERE kind = ? ORDER BY created_at DESC LIMIT 8", (_KIND,))
        jobs = [dict(r) for r in await cursor.fetchall()]
        for job in jobs:
            try:
                payload = json.loads(job.pop("payload") or "{}")
            except ValueError:
                payload = {}
            job["index"] = payload.get("index")
            job["generation"] = payload.get("generation")
            job["fingerprint"] = str(payload.get("fingerprint") or "")[:12]
            out[str(job.pop("job_id"))[:16]] = job
    except Exception:
        pass
    return out


__all__ = [
    "ST_QUEUED", "ST_BUILDING", "ST_RUNNING", "ST_CHECKPOINT",
    "ST_PAUSED", "ST_PAUSED_RATE_LIMIT", "ST_PAUSED_PROVIDER",
    "ST_VALIDATING", "ST_VALIDATED", "ST_VALIDATION_FAILED",
    "ST_ACTIVATED", "ST_FAILED", "ST_CANCELLED",
    "graphrag_rebuild_enabled", "maybe_schedule_rebuilds", "run_job",
    "pause_rebuild", "resume_rebuild", "cancel_rebuild", "rebuild_status",
    "RESUME_TICK_SECONDS", "start_resume_ticker", "resume_tick_once",
]
