"""Epic 60 Фаза D (Section 66.2/66.11, T-480/T-489) — MemoryMaintenanceService.

Два фоновых джоба на ОДНОМ APScheduler (MemoryJobStore, max_instances=1,
coalesce — анти-рейс, прецедент summary_scheduler):

1. merge — слияние повторяющихся эпизодов в общие факты (66.2): KNN-кластеры
   (или точный subject+predicate при FTS-фолбеке) → LLM-слияние (COMPRESS_PROMPT,
   канон-сосед R11 — НОВЫЙ промпт НЕ вводим) → проверка «ничего не потерялось»
   (покрытие уникальных токенов ≥60%) → INSERT производного факта с lineage на
   источники; исходные строки ОСТАЮТСЯ живыми.
   Защищённые факты (65.10) в кластеры не попадают.

2. review — периодический пересмотр (66.11): диагностика точных дублей и
   vec-кластеров ≥0.95 (только КАНДИДАТ на дедуп — событие, без записи и без
   удаления), глобальный выброс истёкших, выброс unconfirmed старше
   GRAPH_UNCONFIRMED_RETENTION_DAYS, усечение лога сжатий.

MEMORY-04 (C-3 §3.4/§3.5, MEM-04.3/04.5/04.6, audit A0 §5): ни слияние, ни
пересмотр НЕ удаляют исходные факты — ни при каком значении гейта
(§3.4.1.1 п.1/п.9, §3.6: разрушающая ветка удалена из кода, а не спрятана за
флагом). `delete_graph_fact` в этом модуле не вызывается вообще; физическое
удаление остаётся только у явного пользовательского delete/forget и у
retention-политик (`purge_expired_graph_facts`/`purge_unconfirmed_graph_facts`
в `database`). Сходство (cosine) — не доказательство и не решение: оно может
только предложить кандидата на дедуп. Каждое решение пишется явным кодом из
`MEMORY_DECISIONS` (`summary_memory`): слияние — ADD производного факта +
lineage в обе стороны (`source_ids`/`derived_from` forward, `supersedes` +
`freshness_status='superseded'` backward), склейка/vec-дубль — NOOP-наблюдение
(`memory_dedupe_candidate`).

Гейт спрашивается в `merge_episodes`, `_merge_chat`, `review` и
`_glue_vec_dups` (per-chat, `mca_gates.memory_maintenance_policy_enabled`,
default **OFF до приёмки**). OFF → консолидация ИНЕРТНА: ни слияний, ни
склеек, ни lineage, ни удалений — только honest skip-код в логе; retention-
фазы review (истёкшие/unconfirmed/усечение лога) работают как раньше. ON →
путь выше (неразрушающее слияние с lineage + кандидаты на дедуп).
"""
import asyncio
import datetime
import json
import logging
import os
import time
from pathlib import Path

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings
from services import hot_config as hot
from services import retention_policy
from services.graph_stoplist import METAFACT_PENALTY_IMPORTANCE
from services.llm_client import LLMError
from services.summary_memory import MEMORY_DECISIONS, _TOKEN_RE
from services.summary_prompts import COMPRESS_PROMPT

logger = logging.getLogger(__name__)

# ── ASAP 8 (F6, §13.3/DoD «heartbeat observable»): честный штамп последнего
# тика (ts + due + enabled-гейт на момент тика). v6 C06A: штамп ПЕРСИСТЕНТЕН
# (durable-строка в `task_jobs`, см. _persist_heartbeat_tick) — рестарт больше
# не превращает Status в ложное «Heartbeat ещё не запускался»; in-memory dict —
# кэш-вид для Status intent_snapshot (fail-open). Durable-событие на каждый тик
# не эмитится (notable-only контракт mca-13) — строка состояния, не событие.
_heartbeat_last_tick: dict = {"ts": None, "due": 0, "enabled": None}

# v6 C06A: живая ссылка на запущенный сервис (для registered/next_tick из
# статусного payload — раздельные факты «джоба в планировщике» vs «гейт»).
_active_service: "MemoryMaintenanceService | None" = None


def _direct_chat_service_singleton():
    """Singleton DirectChatService (DI из bot.py → handlers.direct_chat).
    Ленивый импорт handlers из services — прецедент direct_chat_service
    (`from handlers.summary import ...`). None → Direct-модуль не поднят."""
    try:
        from handlers import direct_chat as _dc
        return getattr(_dc, "_service", None)
    except Exception:
        return None

_MERGE_COVERAGE_MIN = 0.6      # 66.2: доля уникальных токенов слитого от исходных
_MERGE_CLUSTER_SIM = 0.85      # 66.2: кластер-порог KNN-сходства (эпизоды одной темы)
_MERGE_KNN_K = 5               # соседей на кластеризацию
_REVIEW_VEC_BATCH = 100        # потолок фактов чата на vec-склейку (66.11)
_REVIEW_GLUE_SIM = 0.95        # 66.11: vec-кластеры ≥0.95 → кандидат на дедуп

# MEMORY-04 (C-3 §3.4): коды решений этого модуля. Полный набор — в
# `summary_memory.MEMORY_DECISIONS`; здесь только те, что реально возникают в
# обслуживании: слияние = ADD производного факта, наблюдение дубля = NOOP.
DECISION_ADD = "add"
DECISION_NOOP = "noop"
# Событие-наблюдение «похожие факты» (R17: только id/числа/коды). НЕ решение:
# при гейте политики сходство вектора перестаёт быть доказательством (MEM-04.4).
_CANDIDATE_EVENT = "memory_dedupe_candidate"


def _source_id_list(raw) -> list:
    """`graph_facts.source_ids` → список int (битое/не-список значение → [])."""
    if raw in (None, ""):
        return []
    data = raw
    if isinstance(raw, str):
        try:
            import json as _json
            data = _json.loads(raw)
        except (ValueError, TypeError):
            return []
    if not isinstance(data, (list, tuple)):
        return []
    out: list[int] = []
    for value in data:
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            continue
    return out


async def _policy_enabled(chat_id: int | None = None) -> bool:
    """Effective гейт MEMORY-04 (единственный резолвер — `mca_gates`).

    OFF/ошибка резолва → False (fail-closed в паритет baseline, скрытого
    включения нет)."""
    try:
        from services import mca_gates
        return bool(await mca_gates.memory_maintenance_policy_enabled(chat_id))
    except Exception:                                  # pragma: no cover
        return False


def _emit_dedupe_candidate(chat_id: int, kind: str, fact_ids,
                           similarity: float | None = None) -> None:
    """Кандидат на дедуп как событие (`memory_dedupe_candidate`).

    Ничего не пишет в граф и не меняет вес: только диагноз «эти строки похожи»
    с id ближайшего кандидата (§3.4). `reason_code` — из штатного каталога
    §17.2 (`insufficient_evidence`: сходства недостаточно для решения), вид
    кандидата — в `stage`/`usage_json`. Fail-open (событие не рвёт тик)."""
    try:
        from services import mca_events
        mca_events.emit_mca_event(
            _CANDIDATE_EVENT, outcome="skipped",
            component="memory_maintenance",
            stage=f"dedupe_candidate:{kind}",
            reason_code="insufficient_evidence", chat_id=int(chat_id),
            entity_ids=[int(f) for f in fact_ids][:8],
            usage_json={"kind": str(kind), **(
                {"similarity": round(float(similarity), 3)}
                if similarity is not None else {})})
    except Exception:
        pass

# MCA-16 (T-5003): тик review опыта (сек); код-константа (Δ каталога = 0).
_EXPERIENCE_REVIEW_TICK_SECONDS = 900

# MCA-09 (T-5026, ADR-1028-16 D5/D10): лёгкий heartbeat due-намерений (сек);
# код-константа (Δ каталога = 0). Тик только ищет due-намерения и порождает
# кандидатов — БЕЗ LLM и без чтения большого окна сообщений.
_INTENT_HEARTBEAT_TICK_SECONDS = 300

# mca-18 (T-5084, ADR-1028-18 D8): тик фонового идемпотентного разбора
# `persona_traits` (сек; код-константа, Δ каталога = 0). Повтор = no-op по
# `legacy_ref`; bounded batch; «весь архив до включения перерабатывать не
# требуется».
_LEGACY_TRAITS_PARSE_TICK_SECONDS = 3600

# ASAP 8 F8 (E4/§28.19): периодический re-probe embed-деградации + backfill
# text-only backlog БЕЗ read-трафика (сек; код-константа, Δ каталога = 0).
# Совпадает с `_VEC_REACTIVATE_INTERVAL` (10 мин) — re-probe без read-пути.
_EMBED_RECOVERY_TICK_SECONDS = 600

# ASAP 8 v6.3 (B01): тик initiative opportunity observer (сек; код-константа,
# Δ каталога = 0). Scan-фаза дёшевa (курсор по smart_messages, без LLM);
# semantic evaluation — bounded по расписанию внутри job.
_INITIATIVE_OBSERVER_TICK_SECONDS = 300

# v6.3 B01: честный штамп последнего тика наблюдателя (in-memory вид для
# Status; durable-состояние — payload durable-задачи initiative.observe).
_initiative_observer_last_tick: dict = {"ts": None, "status": None,
                                        "observed": 0, "opportunities": 0}


def _experience_review_tick_enabled() -> bool:
    """K1+K3+UI-настройка review опыта (fail-closed, никогда не бросает)."""
    try:
        from services import mca_experience_jobs as jobs
        return bool(jobs.review_enabled())
    except Exception:      # pragma: no cover - защитная ветка
        return False


def _legacy_traits_parse_tick_enabled() -> bool:
    """mca-18 K3: фоновый разбор `persona_traits` (fail-closed)."""
    try:
        from services import mca_gates
        return bool(mca_gates.legacy_traits_migration_enabled())
    except Exception:      # pragma: no cover - защитная ветка
        return False


def _intent_heartbeat_tick_enabled() -> bool:
    """K1+K2 Intent-heartbeat (fail-closed, никогда не бросает).

    v6 C06A: гейт читается ТИКОМ на каждом заходе (hot, без рестарта);
    регистрация джобы от гейта больше не зависит (см. start()) — тумблер
    симметричен: OFF-hot останавливает работу тика, ON-hot запускает."""
    try:
        from services import mca_gates
        return bool(mca_gates.intent_heartbeat_enabled())
    except Exception:      # pragma: no cover - защитная ветка
        return False


# ── v6 C06A: durable liveness-штамп тика ────────────────────────────────────
# Носитель — СУЩЕСТВУЮЩАЯ durable-очередь `task_jobs` (v14): ОДНА строка с
# фиксированным PK, status='completed' (терминальный — супервайзер её не
# подбирает как работу), heartbeat_at = ts последнего тика, payload =
# {due, enabled}. Перезапись — UPSERT по PK; НЕ per-intent task_jobs
# (контракт mca-09 не тронут), новой таблицы/миграции нет.
_HEARTBEAT_LIVENESS_JOB_ID = "intent_heartbeat_liveness"
_HEARTBEAT_LIVENESS_OWNER = "memory_maintenance"
_HEARTBEAT_LIVENESS_KIND = "intent_heartbeat_liveness"


async def _persist_heartbeat_tick(db, *, ts: int, due: int,
                                  enabled: bool) -> None:
    """UPSERT durable-штампа последнего тика (fail-open: телеметрия не должна
    ронять тик; сбой → WARNING, in-memory штамп остаётся честным)."""
    if db is None:
        return
    try:
        payload = json.dumps({"due": int(due), "enabled": bool(enabled)},
                             ensure_ascii=False)

        async def _body(conn):
            await conn.execute(
                "INSERT INTO task_jobs (job_id, owner, kind, status, "
                "payload, attempt, max_attempts, created_at, updated_at, "
                "heartbeat_at, finished_at) VALUES (?, ?, ?, 'completed', "
                "?, 0, 1, ?, ?, ?, ?) ON CONFLICT(job_id) DO UPDATE SET "
                "payload = excluded.payload, updated_at = excluded.updated_at, "
                "heartbeat_at = excluded.heartbeat_at",
                (_HEARTBEAT_LIVENESS_JOB_ID, _HEARTBEAT_LIVENESS_OWNER,
                 _HEARTBEAT_LIVENESS_KIND, payload, ts, ts, ts, ts))

        await db.write_transaction(_body,
                                   op_name="intent_heartbeat_liveness")
    except Exception:
        logger.warning("[c06a] heartbeat liveness persist failed",
                       exc_info=True)


async def _load_heartbeat_tick(db) -> dict | None:
    """Прочитать durable-штамп (None — нет строки/БД недоступна; fail-open)."""
    if db is None:
        return None
    try:
        cursor = await db.db.execute(
            "SELECT heartbeat_at, payload FROM task_jobs WHERE job_id = ?",
            (_HEARTBEAT_LIVENESS_JOB_ID,))
        row = await cursor.fetchone()
        if row is None or row["heartbeat_at"] is None:
            return None
        due, enabled = 0, None
        try:
            data = json.loads(row["payload"] or "{}")
            due = int(data.get("due") or 0)
            enabled = data.get("enabled")
        except Exception:
            pass
        return {"ts": int(row["heartbeat_at"]), "due": due,
                "enabled": enabled}
    except Exception:
        logger.warning("[c06a] heartbeat liveness load failed",
                       exc_info=True)
        return None


def intent_heartbeat_job_info() -> dict:
    """v6 C06A: раздельные факты «registered»/«next_tick» из ЖИВОГО
    планировщика (для Status): registered = джоба есть у запущенного сервиса
    (после start() — всегда, гейт внутри тика); next_tick = next_run_time.
    Сервис не запущен → честное {registered: False, next_tick: None}."""
    svc = _active_service
    if svc is None:
        return {"registered": False, "next_tick": None}
    try:
        job = svc._scheduler.get_job(
            MemoryMaintenanceService.JOB_INTENT_HEARTBEAT_ID)
    except Exception:      # pragma: no cover — планировщик не работоспособен
        return {"registered": False, "next_tick": None}
    if job is None:
        return {"registered": False, "next_tick": None}
    nrt = getattr(job, "next_run_time", None)
    try:
        next_ts = int(nrt.timestamp()) if nrt is not None else None
    except Exception:      # pragma: no cover — экзотический tz-объект
        next_ts = None
    return {"registered": True, "next_tick": next_ts}


class MemoryMaintenanceService:
    """Фоновое обслуживание памяти: слияние эпизодов (66.2) + пересмотр (66.11)."""

    JOB_MERGE_ID = "graph_episode_merge"
    JOB_REVIEW_ID = "graph_review"
    JOB_WAL_ID = "db_wal_checkpoint"   # Epic 64: удержание -wal от разрастания
    # MCA-16 (T-5003/D7): тик пакетного review опыта — отдельный тип job в
    # СУЩЕСТВУЮЩЕЙ очереди; тик лишь проверяет каденцию (hot, без рестарта).
    JOB_EXPERIENCE_REVIEW_ID = "experience_review_tick"
    # MCA-09 (T-5026/D1): лёгкий heartbeat due-намерений — тот же существующий
    # планировщик (второй очереди/планировщика нет; per-intent task_jobs не
    # создаются — durable-состояние в `mca_intents`, догон следующим сканом).
    JOB_INTENT_HEARTBEAT_ID = "intent_heartbeat_tick"
    # mca-18 (T-5084/D8): тик legacy-разбора persona_traits — та же очередь;
    # идемпотентность по `legacy_ref`, K3 OFF → джоб не регистрируется.
    JOB_LEGACY_TRAITS_PARSE_ID = "legacy_traits_parse_tick"
    # ASAP 8 F8 (E4/§28.19): re-probe embed-деградации + backfill text-only
    # backlog — тот же существующий планировщик обслуживания; здоровье
    # embeddings не зависит от других джобов и read-трафика (почти бесплатен
    # при здоровом vec: cadence-гейт внутри `embed_recovery_tick`).
    JOB_EMBED_RECOVERY_ID = "embed_recovery_tick"
    # ASAP 8 v6.3 (B01): тик initiative opportunity observer — тот же
    # планировщик; gate читается тиком на каждом заходе (прецедент
    # intent_heartbeat: регистрация всегда, OFF-hot → тик инертен).
    JOB_INITIATIVE_OBSERVER_ID = "initiative_observer_tick"

    def __init__(self, db, memory, llm, bot=None) -> None:
        self.db = db
        self.memory = memory
        self.llm = llm
        # MCA-09 (T-5026/T-5038): bot — только для передачи due-кандидатов в
        # единый вход инициативы (тот же транспорт); None → кандидаты честно
        # логируются без отправки.
        self.bot = bot
        self._scheduler = AsyncIOScheduler(timezone=hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE))

    def start(self) -> None:
        if hot.get("flags.graph_episode_merge_enabled", settings.GRAPH_EPISODE_MERGE_ENABLED):
            self._scheduler.add_job(
                self._tick_merge,
                IntervalTrigger(
                    days=hot.get("limits.graph_episode_merge_interval_days", settings.GRAPH_EPISODE_MERGE_INTERVAL_DAYS),
                    timezone=hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE)),
                id=self.JOB_MERGE_ID, replace_existing=True,
                max_instances=1, coalesce=True)
        if hot.get("flags.graph_review_enabled", settings.GRAPH_REVIEW_ENABLED):
            self._scheduler.add_job(
                self._tick_review,
                IntervalTrigger(
                    days=hot.get("limits.graph_review_interval_days", settings.GRAPH_REVIEW_INTERVAL_DAYS),
                    timezone=hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE)),
                id=self.JOB_REVIEW_ID, replace_existing=True,
                max_instances=1, coalesce=True)
        # Epic 64: периодический WAL-checkpoint(TRUNCATE) — без него -wal
        # разрастался (наблюдалось 18 МБ при БД 43 МБ).
        if hot.get("flags.db_wal_checkpoint_enabled", settings.DB_WAL_CHECKPOINT_ENABLED):
            self._scheduler.add_job(
                self._tick_wal_checkpoint,
                IntervalTrigger(
                    hours=hot.get("limits.db_wal_checkpoint_hours", settings.DB_WAL_CHECKPOINT_HOURS),
                    timezone=hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE)),
                id=self.JOB_WAL_ID, replace_existing=True,
                max_instances=1, coalesce=True)
        # MCA-16 (T-5003, ADR-1028-15 D7): тик review опыта — тот же
        # планировщик обслуживания (второй очереди/планировщика нет). Тик
        # каждые 15 минут: каденция (hourly/daily/weekly) и UI-настройка
        # learning читаются hot при каждом тике → применяются без рестарта.
        if _experience_review_tick_enabled():
            self._scheduler.add_job(
                self._tick_experience_review,
                IntervalTrigger(
                    seconds=_EXPERIENCE_REVIEW_TICK_SECONDS,
                    timezone=hot.get("limits.summary_timezone",
                                     settings.SUMMARY_TIMEZONE)),
                id=self.JOB_EXPERIENCE_REVIEW_ID, replace_existing=True,
                max_instances=1, coalesce=True)
        # MCA-09 (T-5026, ADR-1028-16 D5) + v6 C06A: лёгкий heartbeat
        # due-намерений — тот же планировщик. Раньше джоба регистрировалась
        # ТОЛЬКО если гейт был ON при старте процесса → hot-ON тумблера
        # не работал до рестарта (асимметрия toggle, R1 RCA C06A). Теперь
        # джоба регистрируется ВСЕГДА (прецедент embed_recovery), а гейт
        # K1/K2 читается тиком на каждом заходе: OFF-hot останавливает
        # работу тика (mca_intents.heartbeat_tick инертен, 0 SQL), ON-hot
        # запускает её ≤300 с. Semantics симметричны, рестарт не нужен.
        self._scheduler.add_job(
            self._tick_intent_heartbeat,
            IntervalTrigger(
                seconds=_INTENT_HEARTBEAT_TICK_SECONDS,
                timezone=hot.get("limits.summary_timezone",
                                 settings.SUMMARY_TIMEZONE)),
            id=self.JOB_INTENT_HEARTBEAT_ID, replace_existing=True,
            max_instances=1, coalesce=True)
        # mca-18 (T-5084, ADR-1028-18 D8): тик идемпотентного разбора
        # persona_traits (K3 OFF → джоб не регистрируется — бит-в-бит).
        if _legacy_traits_parse_tick_enabled():
            self._scheduler.add_job(
                self._tick_legacy_traits_parse,
                IntervalTrigger(
                    seconds=_LEGACY_TRAITS_PARSE_TICK_SECONDS,
                    timezone=hot.get("limits.summary_timezone",
                                     settings.SUMMARY_TIMEZONE)),
                id=self.JOB_LEGACY_TRAITS_PARSE_ID, replace_existing=True,
                max_instances=1, coalesce=True)
        # ASAP 8 F8 (E4/§28.19): re-probe embed-деградации + backfill text-only
        # backlog — регистрируется ВСЕГДА (не зависит от других флагов):
        # recovery памяти не должен зависеть от read-трафика/прочих джобов.
        self._scheduler.add_job(
            self._tick_embed_recovery,
            IntervalTrigger(
                seconds=_EMBED_RECOVERY_TICK_SECONDS,
                timezone=hot.get("limits.summary_timezone",
                                 settings.SUMMARY_TIMEZONE)),
            id=self.JOB_EMBED_RECOVERY_ID, replace_existing=True,
            max_instances=1, coalesce=True)
        # ASAP 8 v6.3 (B01): тик initiative opportunity observer — регистри-
        # руется ВСЕГДА (прецедент intent_heartbeat C06A): gate
        # flags.initiative_observer_enabled + K1 читается тиком на каждом
        # заходе → toggle симметричен без рестарта.
        self._scheduler.add_job(
            self._tick_initiative_observer,
            IntervalTrigger(
                seconds=_INITIATIVE_OBSERVER_TICK_SECONDS,
                timezone=hot.get("limits.summary_timezone",
                                 settings.SUMMARY_TIMEZONE)),
            id=self.JOB_INITIATIVE_OBSERVER_ID, replace_existing=True,
            max_instances=1, coalesce=True)
        self._scheduler.start()
        # v6 C06A: сервис запущен → registered/next_tick доступны Status;
        # durable-штамп последнего тика восстанавливается (fail-open) —
        # рестарт больше не выглядит как «тик ещё не был».
        global _active_service
        _active_service = self
        self._startup_tasks = []
        try:
            _loop = asyncio.get_running_loop()
        except RuntimeError:
            _loop = None
        if _loop is not None:
            self._startup_tasks.append(
                _loop.create_task(self._hydrate_heartbeat_liveness()))
        logger.info(
            "MemoryMaintenance started (merge=%s/%dd, review=%s/%dd, "
            "wal=%s/%dh, embed_reprobe=%ds, intent_hb=%ds[always-on])",
            hot.get("flags.graph_episode_merge_enabled", settings.GRAPH_EPISODE_MERGE_ENABLED),
            hot.get("limits.graph_episode_merge_interval_days", settings.GRAPH_EPISODE_MERGE_INTERVAL_DAYS),
            hot.get("flags.graph_review_enabled", settings.GRAPH_REVIEW_ENABLED),
            hot.get("limits.graph_review_interval_days", settings.GRAPH_REVIEW_INTERVAL_DAYS),
            hot.get("flags.db_wal_checkpoint_enabled", settings.DB_WAL_CHECKPOINT_ENABLED),
            hot.get("limits.db_wal_checkpoint_hours", settings.DB_WAL_CHECKPOINT_HOURS),
            _EMBED_RECOVERY_TICK_SECONDS,
            _INTENT_HEARTBEAT_TICK_SECONDS)

    async def _hydrate_heartbeat_liveness(self) -> None:
        """v6 C06A: восстановить durable-штамп тика в in-memory вид для
        Status (fail-open: нет строки/БД недоступна → штамп остаётся пустым)."""
        stamp = await _load_heartbeat_tick(self.db)
        if stamp is not None:
            _heartbeat_last_tick.update(stamp)

    async def _tick_wal_checkpoint(self) -> None:
        """Epic 64: PRAGMA wal_checkpoint(TRUNCATE) — сброс -wal в основной файл.

        B-MCA01-1 (ADR-1027-3 D3): checkpoint — операция над ОБЩИМ
        соединением, выполняется под single-writer (`serialized()`), чтобы не
        интерливить с чужой открытой транзакцией."""
        try:
            async with self.db.serialized():
                cursor = await self.db.db.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)")
                row = await cursor.fetchone()
                await self.db.db.commit()
            logger.info("WAL checkpoint done | busy=%s log_pages=%s checkpointed=%s",
                        row[0] if row else "?", row[1] if row else "?",
                        row[2] if row else "?")
        except Exception:
            logger.warning("WAL checkpoint failed", exc_info=True)

    async def _tick_merge(self) -> None:
        try:
            await self.merge_episodes()
        except LLMError as exc:
            # 66.2: LLMError → пропуск прогона (следующий цикл через N дней).
            logger.warning("episode merge: LLM failed — run skipped | error=%s", exc)
        except Exception:
            logger.warning("episode merge: failed", exc_info=True)

    async def _tick_review(self) -> None:
        try:
            await self.review()
        except Exception:
            logger.warning("graph review: failed", exc_info=True)

    async def _tick_experience_review(self) -> None:
        """MCA-16 (T-5003): тик пакетного review опыта (durable job).

        Каденция/настройка читаются hot на каждом тике — применение без
        рестарта. Ошибка не рвёт планировщик; OFF → честный `disabled`.
        ASAP 8 v6.3 (B02): semantic extractor получает СУЩЕСТВУЮЩИЙ LLM-клиент
        (DI из DirectChatService-синглтона); клиент недоступен → семантическая
        стадия честно `unavailable` (детерминированный контур работает)."""
        try:
            from services import mca_experience_jobs as jobs
            service = _direct_chat_service_singleton()
            llm = getattr(service, "llm", None) if service is not None \
                else None
            status = await jobs.tick_experience_review(self.db, llm=llm)
            if status not in ("not_due", "disabled", "running"):
                logger.info("[mca16] experience review tick | status=%s",
                            status)
        except Exception:
            logger.warning("[mca16] experience review tick failed",
                           exc_info=True)

    async def _tick_initiative_observer(self) -> None:
        """ASAP 8 v6.3 (B01, REQ-B01): тик initiative opportunity observer.

        Сигналы из обычного чата НЕ зависят от Direct entrypoint: observer
        читает human-corpus `smart_messages` напрямую; Writer переиспользуется
        (DirectChatService-синглтон), при его недоступности — явный статус
        `initiative_writer_unavailable` (внутри job), не молчание. Ошибка не
        рвёт планировщик; master OFF → честный `disabled`."""
        try:
            from services import initiative_observer as observer
            service = _direct_chat_service_singleton()
            llm = getattr(service, "llm", None) if service is not None \
                else None
            status = await observer.observe_tick(
                self.db, bot=self.bot, writer_service=service, llm=llm,
                # P0 corrective 25.10.2026 (F2/F3): тот же live-резолвер, что
                # у Direct/Summary; без него — прежние author_name.
                alias_resolver=getattr(service, "aliases", None))
            counters = {}
            try:
                active = await observer.get_active_observe(self.db)
                if active is not None:
                    counters = json.loads(
                        (active.get("payload") or "{}")).get("counters") or {}
            except Exception:
                counters = {}
            _initiative_observer_last_tick["ts"] = int(time.time())
            _initiative_observer_last_tick["status"] = status
            _initiative_observer_last_tick["observed"] = int(
                counters.get("observed") or 0)
            _initiative_observer_last_tick["opportunities"] = int(
                counters.get("opportunities") or 0)
            if status not in ("disabled", "not_due", "running"):
                logger.info("[b01] initiative observer tick | status=%s "
                            "observed=%s opportunities=%s", status,
                            _initiative_observer_last_tick["observed"],
                            _initiative_observer_last_tick["opportunities"])
            else:
                logger.debug("[b01] initiative observer tick | status=%s",
                             status)
        except Exception:
            logger.warning("[b01] initiative observer tick failed",
                           exc_info=True)

    async def _tick_intent_heartbeat(self) -> None:
        """MCA-09 (T-5026) + ASAP 8 F6 (§13.2/§28.15): heartbeat due-намерений
        с ГЕНЕРАЦИЕЙ и отправкой инициативной реплики.

        Due-скан SQL по `mca_intents` (скан — без чтения окна) → кандидаты в
        единый вход инициативы. F6: перед решением строятся СВЕЖИЕ условия из
        реального чата (не дефолтные флаги, §18D); REPLY генерирует текст
        СУЩЕСТВУЮЩИЙ Direct-контур (L1-решение → L2 Writer, writer_service);
        неспособность сгенерировать → терминальный bounded `writer_failed`
        (не бесконечный candidate_ready/defer). Расход LLM учитывается
        существующим worker-budget (`llm_calls`). Гигиена (expire/archive/
        prune) — в `heartbeat_tick`. Ошибка не рвёт планировщик; OFF →
        `disabled`."""
        try:
            from services import mca_gates
            from services import mca_intents
            stats = await mca_intents.get_service(self.db).heartbeat_tick()
            due = list(stats.get("due") or [])
            enabled = bool(stats.get("enabled"))
            # v6 C06A (R1/R3 RCA): «мёртвый» vs «праздный» различимы — тик
            # пишет INFO на КАЖДЫЙ заход (в т.ч. пустой due=0); гейт OFF →
            # DEBUG (инертный тик не должен спамить журнал).
            if enabled:
                logger.info(
                    "[mca09] intent heartbeat tick ran | due=%d expired=%d "
                    "archived=%d", len(due), stats.get("expired", 0),
                    stats.get("archived", 0))
            else:
                logger.debug("[mca09] intent heartbeat tick | gate OFF")
            _heartbeat_last_tick["ts"] = int(time.time())
            _heartbeat_last_tick["due"] = len(due)
            _heartbeat_last_tick["enabled"] = enabled
            # v6 C06A: durable-штамп — последний тик переживает рестарт.
            await _persist_heartbeat_tick(
                self.db, ts=_heartbeat_last_tick["ts"], due=len(due),
                enabled=enabled)
            # Кандидаты — в ЕДИНЫЙ вход инициативы (тот же Decision/транспорт).
            # F6 (§28.15): генерация текста — СУЩЕСТВУЮЩИМ Direct-контуром
            # (singleton DI из bot.py → handlers.direct_chat._service);
            # сервис недоступен (Direct-модуль не поднят) → честный WARN,
            # кандидаты не решаются (heartbeat не выдаёт candidate_ready
            # за генерацию); intent'ы ограничены expiry/hygiene.
            service = _direct_chat_service_singleton()
            if due and self.bot is not None and service is None:
                # B01.5: недоступность переиспользуемого Writer — явный
                # статус/событие `initiative_writer_unavailable`, не молчание
                # (кандидаты остаются due; intent-жизненный цикл не зависит
                # от Direct-trigger-gate).
                try:
                    from services import mca_events
                    mca_events.emit_mca_event(
                        "initiative_writer_unavailable", outcome="skipped",
                        component="initiative", stage="writer:unavailable",
                        due=len(due))
                except Exception:
                    pass
                logger.warning(
                    "[f6] direct chat service unavailable — initiative "
                    "decisions skipped | due=%d", len(due))
            if due and self.bot is not None and service is not None and \
                    mca_gates.intent_decision_enabled():
                from services.direct_chat_service import (
                    build_initiative_situation, handle_initiative)
                for candidate in due:
                    await self._run_initiative_candidate(
                        mca_intents, candidate, service,
                        build_initiative_situation, handle_initiative)
        except Exception:
            logger.warning("[mca09] intent heartbeat tick failed",
                           exc_info=True)

    async def _run_initiative_candidate(self, mca_intents, candidate,
                                        service, situation_builder,
                                        initiative_entry) -> None:
        """F6: один due-кандидат → свежая ситуация (§18D) → единый вход
        инициативы с writer_service (генерация + recheck + send). Бюджет
        LLM-вызовов — существующий worker-budget (`llm_calls`, global+chat);
        исчерпан → кандидат остаётся due без решения (без LLM-расхода).
        Никогда не бросает (один кандидат не рвёт тик).

        INIT-COORD (03.11.2026): координация публикации идёт ДО траты
        LLM-бюджета — порядок precheck → бронь → `claimed→sending`
        (`publish_guard`) → release. Отказ = намерение остаётся
        `pending`/`deferred` (существующее планирование перепроверит его на
        свежем контексте), LLM-вызов не оплачен, второго текста нет."""
        try:
            from services import publication_coordination as _pubmod
            from services import worker_budget
            from services.direct_chat_service import (
                build_fresh_recheck_context)
            row = None
            if candidate.intent_id:
                row = await mca_intents.get_service(
                    self.db).store.get_intent(candidate.intent_id)
            if row is None or str(row.get("status") or "") not in (
                    "pending", "deferred"):
                return
            chat_id = candidate.chat_id
            # §18D pre-decision: разговор ушёл вперёд — вопрос закрыт (A15);
            # терминальные не решаются.
            try:
                fresh = await build_fresh_recheck_context(self.db, chat_id,
                                                          row)
            except Exception:
                fresh = None
            if fresh is not None and fresh.already_answered:
                await mca_intents.get_service(self.db).close(
                    candidate.intent_id, status="fulfilled",
                    reason_code="already_answered")
                logger.info(
                    "[f6] intent answered meanwhile — closed | chat=%s",
                    chat_id)
                return
            publication = await _pubmod.open_text_publication(
                self.db, chat_id,
                holder_ref=str(candidate.intent_id or "chat:%s" % chat_id))
            if not publication.granted:
                logger.info(
                    "[f6] publication conflict — initiative deferred | "
                    "chat=%s | reason=%s | detail=%s", chat_id,
                    publication.reason, publication.detail or "-")
                return
            status = "error"
            try:
                if not await worker_budget.consume(None, "global",
                                                   "llm_calls", 1):
                    logger.info(
                        "[f6] worker budget exhausted — initiative deferred "
                        "| chat=%s", chat_id)
                    return
                if not await worker_budget.consume(None, f"chat:{chat_id}",
                                                   "llm_calls", 1):
                    logger.info(
                        "[f6] chat budget exhausted — initiative deferred | "
                        "chat=%s", chat_id)
                    return
                situation = await situation_builder(self.db, chat_id, row)
                result = await initiative_entry(
                    bot=self.bot, chat_id=chat_id, situation=situation,
                    candidates=[candidate], db=self.db, writer_service=service,
                    publish_guard=publication.guard)
                status = str((result or {}).get("status") or "error")
                logger.info(
                    "[mca09] initiative candidate | chat=%s | status=%s",
                    chat_id, status)
            finally:
                await publication.close(published=(status == "sent"))
        except Exception:
            logger.warning("[f6] initiative candidate failed — skipped",
                           exc_info=True)

    async def _tick_legacy_traits_parse(self) -> None:
        """mca-18 (T-5084, ADR-1028-18 D8): идемпотентный разбор
        `persona_traits` → TraitObservation/BehaviorRule. Повтор = no-op по
        `legacy_ref`; bounded batch; ошибки не рвут планировщик. K3 OFF →
        `disabled` (джоб вообще не регистрируется)."""
        try:
            from services import mca_self_model as msm
            stats = await msm.run_legacy_traits_parse(self.db)
            if stats.get("parsed"):
                logger.info("[mca18] legacy traits parse | parsed=%s "
                            "skipped=%s unverified=%s", stats.get("parsed"),
                            stats.get("skipped"), stats.get("unverified"))
        except Exception:
            logger.warning("[mca18] legacy traits parse tick failed",
                           exc_info=True)

    async def _tick_embed_recovery(self) -> None:
        """ASAP 8 F8 (E4/§28.19): периодический re-probe embed-деградации +
        backfill text-only backlog БЕЗ read-трафика (раньше `_ensure_vec_retry`
        триггерился только read-путём). Каденция/гейты — внутри
        `memory.embed_recovery_tick` (re-probe ≤1/10 мин; backfill bounded);
        при здоровом vec и пустом backlog тик почти бесплатен. Ошибка не рвёт
        планировщик. memory-двойник без метода → no-op (совместимость)."""
        try:
            tick = getattr(self.memory, "embed_recovery_tick", None)
            if tick is None:
                return
            status = await tick()
            if status.get("recovered") or status.get("backfilled"):
                logger.info(
                    "[f8] embed recovery tick | recovered=%s backfilled=%s "
                    "backlog_archive=%s backlog_graph=%s",
                    status.get("recovered"), status.get("backfilled"),
                    status.get("backlog_archive"),
                    status.get("backlog_graph"))
        except Exception:
            logger.warning("[f8] embed recovery tick failed", exc_info=True)

    # ── 66.2 (T-480): слияние повторяющихся эпизодов ──────────────

    async def merge_episodes(self) -> int:
        """Слияние по всем чатам; потолок GRAPH_EPISODE_MERGE_BATCH кластеров
        за прогон. Возвращает число слитых кластеров.

        Гейт `MCA_MEMORY_MAINTENANCE_POLICY_ENABLED` спрашивается на КАЖДЫЙ
        чат (per-chat override, §5.2.1): OFF → консолидация ИНЕРТНА (ни записи,
        ни удаления; один honest skip-код в логе), ON → неразрушающее слияние
        с lineage. Разрушающего legacy-пути в коде нет ни при каком значении
        гейта (§3.4.1.1 п.1/п.9, §3.6).
        """
        budget = hot.get("limits.graph_episode_merge_batch", settings.GRAPH_EPISODE_MERGE_BATCH)
        merged_total = 0
        skipped_chats = 0
        for chat_id in await self.db.get_graph_chat_ids():
            if budget <= 0:
                break
            if not await _policy_enabled(chat_id):
                skipped_chats += 1
                continue
            merged = await self._merge_chat(chat_id, budget)
            budget -= merged
            merged_total += merged
        if skipped_chats:
            logger.info(
                "episode merge: skipped=%d chats | reason=gate_off "
                "(no writes, no deletions)", skipped_chats)
        if merged_total:
            logger.info("episode merge: merged=%d clusters", merged_total)
        return merged_total

    async def _merge_chat(self, chat_id: int, budget: int) -> int:
        now = int(time.time())
        rows = await self.db.get_live_graph_facts(chat_id, now)
        rows = [
            row for row in rows
            if not await self.db.is_fact_protected(chat_id, row["fact"])
        ]
        if len(rows) < 2:
            return 0
        rows = await self._primary_rows(chat_id, rows, now)
        if len(rows) < 2:
            return 0
        clusters = await self._cluster_facts(chat_id, rows, now)
        merged = 0
        for cluster, method in clusters:
            if merged >= budget:
                break
            cluster = cluster[:hot.get("limits.graph_episode_merge_max_facts_per_cluster", settings.GRAPH_EPISODE_MERGE_MAX_FACTS_PER_CLUSTER)]
            if len(cluster) < 2:
                continue
            if await self._merge_cluster(chat_id, cluster, now, method=method):
                merged += 1
        return merged

    async def _primary_rows(self, chat_id: int, rows: list, now: int) -> list:
        """MEMORY-04 (C-3 §3.5): кластеризуются только ПЕРВИЧНЫЕ строки.

        Производный факт (`source_ids` заполнен) — уже обобщение, а не
        независимый сигнал: повторное слияние производной строки с её же
        источниками ничего не добавляет. Строка, поглощённая живым производным
        фактом, тоже не сливается заново (иначе каждый тик создавал бы новый
        агрегат по тем же основаниям). Сами исходные строки при этом
        СОХРАНЯЮТСЯ — они остаются живыми и доступными (MEM-04.3/04.6)."""
        lineage = await self._lineage_columns(
            chat_id, now, [int(row["id"]) for row in rows])
        absorbed: set[int] = set()
        primary: list = []
        for row in rows:
            sources = _source_id_list(
                (lineage.get(int(row["id"])) or {}).get("source_ids"))
            if sources:
                absorbed.update(sources)
                continue
            primary.append(row)
        return [row for row in primary if int(row["id"]) not in absorbed]

    async def _lineage_columns(self, chat_id: int, now: int,
                               fact_ids: list) -> dict:
        """`source_ids`/`valid_from`/`valid_to`/`tg_message_id` живых строк —
        один SELECT (C-3 §3.1: T_event и T_assertion читаются раздельно;
        `now` не подставляется ни в одно из этих полей)."""
        ids = [int(i) for i in fact_ids]
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        try:
            cursor = await self.db.db.execute(
                f"SELECT id, source_ids, valid_from, valid_to, tg_message_id "
                f"FROM graph_facts WHERE chat_id = ? AND id IN ({placeholders})",
                (int(chat_id), *ids))
            return {int(row["id"]): dict(row) for row in await cursor.fetchall()}
        except Exception:
            logger.warning(
                "episode merge: lineage columns unavailable | chat_id=%s",
                chat_id, exc_info=True)
            return {}

    async def _link_lineage(self, chat_id: int, derived_id: int,
                            source_ids: list, now: int, *,
                            verification: str = "verified") -> int:
        """Lineage производного факта FORWARD (C-3 §3.5, MEM-04.5).

        `graph_facts.source_ids` (пишется при INSERT) + EvidenceLink
        `derived_from` на КАЖДЫЙ источник; обратный индекс —
        `provenance.links_derived_from_source()`. `verification` — от метода
        кластеризации: `verified` только для точного кластера, `tentative`
        для собранного сходством (INV-06). Идемпотентно (dedup link);
        provenance OFF → 0 (остаётся `source_ids`). Fail-open: отсутствие
        lineage не должно превращаться в потерю данных.
        `independence='unknown'` — независимость источников НЕ выдумывается."""
        made = 0
        try:
            from services import provenance
            if not provenance.provenance_enabled():
                return 0
            obj = await provenance.resolve_source_ref(
                self.db, provenance.graph_fact_source_ref(chat_id, derived_id))
            if obj is None:
                return 0
            for sid in source_ids:
                if int(sid) == int(derived_id):
                    continue
                ref = await provenance.resolve_source_ref(
                    self.db, provenance.graph_fact_source_ref(chat_id, sid))
                if ref is None:
                    continue
                await provenance.add_evidence_link(
                    self.db, provenance.EvidenceLink(
                        subject_ref_id=obj, source_ref_id=ref,
                        link_type="derived_from", method="direct_reference",
                        verification=verification, independence="unknown",
                        basis="episode_merge", established_at=now))
                made += 1
        except Exception:
            logger.warning(
                "episode merge: lineage link failed — fail-open | chat_id=%s "
                "| fact_id=%s", chat_id, derived_id, exc_info=True)
        return made

    async def _link_backward_supersede(self, chat_id: int, winner_id: int,
                                       source_ids: list, now: int, *,
                                       verification: str = "verified") -> int:
        """Lineage производного факта BACKWARD (C-3 §3.3/§3.5, MEM-04.3/04.5).

        Для каждой поглощённой строки: EvidenceLink `supersedes`
        (победитель ← источник), `freshness_status='superseded'` в
        `mca_provenance_status` (строка НЕ удаляется и не перезаписывается) и
        указатель `graph_facts.supersedes` победителя (однослотовая колонка:
        первый поглощённый). Идемпотентно; provenance OFF → 0. Fail-open."""
        made = 0
        absorbed = [int(sid) for sid in source_ids if int(sid) != int(winner_id)]
        if not absorbed:
            return 0
        try:
            await self.db.db.execute(
                "UPDATE graph_facts SET supersedes = COALESCE(supersedes, ?) "
                "WHERE id = ?", (absorbed[0], int(winner_id)))
            await self.db.db.commit()
        except Exception:
            logger.warning(
                "episode merge: supersedes pointer write failed — fail-open | "
                "fact_id=%s", winner_id, exc_info=True)
        try:
            from services import provenance
            if not provenance.provenance_enabled():
                return made
            obj = await provenance.resolve_source_ref(
                self.db, provenance.graph_fact_source_ref(chat_id, winner_id))
            if obj is None:
                return made
            for sid in absorbed:
                ref = await provenance.resolve_source_ref(
                    self.db, provenance.graph_fact_source_ref(chat_id, sid))
                if ref is None:
                    continue
                await provenance.add_evidence_link(
                    self.db, provenance.EvidenceLink(
                        subject_ref_id=obj, source_ref_id=ref,
                        link_type="supersedes", method="direct_reference",
                        verification=verification, independence="unknown",
                        basis="consolidation", established_at=now))
                existing = await provenance.get_provenance_status(
                    self.db, ref) or {}
                await provenance.set_provenance_status(
                    self.db, ref,
                    origin_status=(existing.get("origin_status") or "unknown"),
                    freshness_status="superseded")
                made += 1
        except Exception:
            logger.warning(
                "episode merge: backward supersede failed — fail-open | "
                "chat_id=%s | fact_id=%s", chat_id, winner_id, exc_info=True)
        return made

    async def _apply_aggregate_validity(self, chat_id: int, fact_id: int,
                                        source_ids: list, now: int) -> None:
        """T_event производного факта (C-3 §3.1/§3.7).

        `valid_from`/`valid_to` ставятся ТОЛЬКО когда их поддерживают ВСЕ
        источники (min/max), иначе NULL: отсутствующая дата ≠ T_assertion ≠
        `now`. Существующее значение не перезаписывается (COALESCE)."""
        info = await self._lineage_columns(chat_id, now, source_ids)
        if len(info) != len(source_ids):
            return
        rows = [info[int(i)] for i in source_ids]
        starts = [row["valid_from"] for row in rows]
        ends = [row["valid_to"] for row in rows]
        valid_from = min(starts) if all(v is not None for v in starts) else None
        valid_to = max(ends) if all(v is not None for v in ends) else None
        if valid_from is None and valid_to is None:
            return
        try:
            await self.db.db.execute(
                "UPDATE graph_facts SET valid_from = COALESCE(valid_from, ?), "
                "valid_to = COALESCE(valid_to, ?) WHERE id = ?",
                (valid_from, valid_to, int(fact_id)))
            await self.db.db.commit()
        except Exception:
            logger.warning(
                "episode merge: aggregate validity write failed — fail-open "
                "| fact_id=%s", fact_id, exc_info=True)

    async def _cluster_facts(self, chat_id: int, rows: list, now: int) -> list:
        """Кластеры ≥2 похожих фактов + МЕТОД кластеризации (MEM-04.5).

        Возврат: список `(cluster, method)`, где method ∈ {`vector`,`exact`}:
        * `vector` — KNN-сходство (cosine ≥ _MERGE_CLUSTER_SIM). Сходство —
          лишь предложение, поэтому производный факт от такого кластера
          рождается `unconfirmed` с lineage `tentative` (INV-06);
        * `exact` — точный subject+predicate (FTS-фолбек — первые два слова):
          это не сходство, а совпадение утверждения.

        Union-find; размер кластера ограничен
        GRAPH_EPISODE_MERGE_MAX_FACTS_PER_CLUSTER."""
        cap = hot.get("limits.graph_episode_merge_max_facts_per_cluster", settings.GRAPH_EPISODE_MERGE_MAX_FACTS_PER_CLUSTER)
        if self.memory._vec_available:
            pairs = []
            try:
                vectors = await self.memory._embed([row["fact"] for row in rows])
            except Exception:
                logger.warning(
                    "episode merge: embed failed — exact subject+predicate fallback")
                return [(grp, "exact")
                        for grp in self._cluster_exact(rows, cap)]
            by_id = {row["id"]: row for row in rows}
            for i, row in enumerate(rows):
                near = await self.memory._dedup_knn(chat_id, vectors[i])
                for item in near[: _MERGE_KNN_K]:
                    other = by_id.get(item["fact_id"])
                    if other is None or other["id"] == row["id"]:
                        continue
                    cosine = 1.0 - item["distance"]
                    if cosine >= _MERGE_CLUSTER_SIM:
                        pairs.append((row["id"], other["id"]))
            return [(grp, "vector")
                    for grp in self._union_clusters(rows, pairs, cap)]
        return [(grp, "exact") for grp in self._cluster_exact(rows, cap)]

    @staticmethod
    def _cluster_exact(rows: list, cap: int) -> list:
        """FTS-фолбек: точный subject+predicate — первые два слова факта."""
        groups: dict[str, list] = {}
        for row in rows:
            words = str(row["fact"]).split()
            key = " ".join(words[:2]).casefold() if len(words) >= 2 else None
            if key:
                groups.setdefault(key, []).append(row)
        return [grp[:cap] for grp in groups.values() if len(grp) >= 2]

    @staticmethod
    def _union_clusters(rows: list, pairs: list, cap: int) -> list:
        parent = {row["id"]: row["id"] for row in rows}
        size = {row["id"]: 1 for row in rows}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a, b in pairs:
            ra, rb = find(a), find(b)
            if ra == rb:
                continue
            if size[ra] + size[rb] > cap:
                continue
            parent[rb] = ra
            size[ra] += size[rb]
        clusters: dict[int, list] = {}
        for row in rows:
            clusters.setdefault(find(row["id"]), []).append(row)
        return [grp for grp in clusters.values() if len(grp) >= 2]

    async def _merge_cluster(self, chat_id: int, cluster: list, now: int, *,
                             method: str = "exact"):
        """LLM-слияние (COMPRESS_PROMPT) + проверка покрытия токенов → INSERT
        (или reuse идентичной живой строки) ПРОИЗВОДНОГО факта с lineage.

        MEMORY-04 (C-3 §3.4.1/§3.5, MEM-04.3/04.5, INV-06) — решение ADD:
        ни одна исходная строка не удаляется НИ ПРИ КАКОМ значении гейта
        (§3.4.1.1 п.1/п.9: разрушающая ветка удалена из кода, а не спрятана
        за флагом). Гейт OFF сюда не доходит: `merge_episodes` пропускает
        консолидацию целиком. Lineage пишется в ОБЕ стороны: forward
        `source_ids` + `derived_from`, backward `supersedes` +
        `freshness_status='superseded'` (для точных кластеров — это замена
        дублей, а не сходство).

        `method='vector'` — кластер собран ТОЛЬКО сходством: производный факт
        рождается `unconfirmed`, lineage `tentative` (сходство не
        доказательство). `method='exact'` — `confirmed`/`verified`.
        Покрытие не прошло → пропуск кластера (WARNING), исходные живут."""
        texts = [str(row["fact"]) for row in cluster]
        source_tokens = {token for text in texts
                         for token in _TOKEN_RE.findall(text.lower())}
        try:
            raw = await self.llm.generate([
                {"role": "system", "content": COMPRESS_PROMPT},
                {"role": "user", "content":
                    "слей эти факты в один, ничего не потеряй:\n"
                    + "\n".join(f"- {t}" for t in texts)}])
        except LLMError as exc:
            logger.warning("episode merge: LLM failed — cluster skipped | error=%s", exc)
            return None
        merged_text = str(raw or "").strip()
        if not merged_text:
            return None
        merged_tokens = set(_TOKEN_RE.findall(merged_text.lower()))
        if source_tokens and \
                len(merged_tokens) < _MERGE_COVERAGE_MIN * len(source_tokens):
            logger.warning(
                "episode merge: coverage check failed (%d%% < %d%%) — cluster "
                "skipped, sources live | chat_id=%s",
                int(100 * len(merged_tokens) / max(1, len(source_tokens))),
                int(100 * _MERGE_COVERAGE_MIN), chat_id)
            return None
        source_ids = sorted({int(row["id"]) for row in cluster})
        origin = ("chat_history" if any(row["origin"] == "chat_history" for row in cluster)
                  else cluster[0]["origin"])
        expiry = (None if any(row["expires_at"] is None for row in cluster)
                  else max(row["expires_at"] for row in cluster))
        weight = max(row["weight"] for row in cluster)
        # S10.18-35 (F5, ADR-1018-5 D2/D3): эпи-мерж НЕ должен «терять»
        # F5-пенальти мета-фактов. Исходные мета-факты записаны с importance=1
        # (срез по subject/object), но пере-вычисление rule_importance('chat_history')
        # дало бы слитой строке 4 → два таких факта набрали бы Σ8 ≥ гейта Сна.
        # Минимально инвазивно: если ВСЕ члены кластера имели imp<=1 → merged
        # imp=METAFACT_PENALTY_IMPORTANCE; иначе прежнее поведение (None →
        # rule_importance), существующие merge-тесты не затрагиваются.
        importance = (
            METAFACT_PENALTY_IMPORTANCE
            if all(int(row["importance"]) <= METAFACT_PENALTY_IMPORTANCE
                   for row in cluster)
            else None)
        targets = {row["target_user"] for row in cluster if row["target_user"]}
        target_user = targets.pop() if len(targets) == 1 else None
        candidate_status = ("unconfirmed" if method == "vector"
                            else "confirmed")
        verification = ("tentative" if method == "vector" else "verified")
        # Идемпотентность: производный факт с тем же текстом уже записан (тик
        # повторился после сбоя между INSERT и журналом) → переиспользуем его, а
        # не плодим дубли. Переиспользуется ТОЛЬКО производная строка
        # (`source_ids` заполнен) — совпадение текста с обычным фактом не даёт
        # права считать его агрегатом.
        existing = await self.db.find_graph_fact_exact(chat_id, merged_text, now)
        reuse_id = None
        if existing is not None:
            known = await self._lineage_columns(
                chat_id, now, [int(existing["id"])])
            if _source_id_list(
                    (known.get(int(existing["id"])) or {}).get("source_ids")):
                reuse_id = int(existing["id"])
        reused = reuse_id is not None
        if reused:
            fact_id = reuse_id
        else:
            fact_id = await self.db.insert_graph_fact(
                chat_id, merged_text, origin, expiry, target_user=target_user,
                weight=weight, importance=importance,
                status=candidate_status,
                source_ids=json.dumps(source_ids))
            if self.memory._vec_available:
                await self.memory._save_graph_fact_embedding(
                    fact_id, chat_id, merged_text, origin, expiry)
        await self._apply_aggregate_validity(chat_id, fact_id, source_ids, now)
        links = await self._link_lineage(
            chat_id, fact_id, source_ids, now, verification=verification)
        backward = 0
        if method == "exact":
            backward = await self._link_backward_supersede(
                chat_id, fact_id, source_ids, now,
                verification=verification)
        for row in cluster:
            await self.db.log_fact_compression(
                chat_id, fact_id, row["fact"], merged_text, "episode_merge")
        logger.info(
            "episode merge: decision=%s%s | method=%s | status=%s | sources=%d "
            "kept=%d lineage=%d backward=%d | chat_id=%s | fact_id=%d",
            DECISION_ADD, " (reuse)" if reused else "", method,
            candidate_status, len(cluster), len(cluster), links, backward,
            chat_id, fact_id)
        return fact_id

    # ── 66.11 (T-489): периодический пересмотр ──────────────────

    async def review(self) -> None:
        """(1) точные дубли и vec-кластеры ≥0.95 → КАНДИДАТ на дедуп (событие
        `memory_dedupe_candidate`, решение NOOP: ни записи, ни удаления),
        у точной группы — ещё и backward-указатель победителю;
        (2) выброс истёкших — глобальный проход (retention, §3.4.1);
        (3) выброс unconfirmed старше retention; (4) усечение лога сжатий.

        Гейт `MCA_MEMORY_MAINTENANCE_POLICY_ENABLED` спрашивается на каждый
        чат: ON — сходство не является ни подтверждением, ни основанием
        инвалидации, склейка ничего не уничтожает; OFF — дедуп-ветка
        ИНЕРТНА (ни записи, ни удаления; один honest skip-код), а retention-
        фазы (2)-(4) продолжают работать: это разные политики.
        Событие-кандидат эмитится не более одного раза на пару за прогон."""
        now = int(time.time())
        candidates = 0
        skipped_dedupe = 0
        emitted: set[tuple] = set()
        for chat_id in await self.db.get_graph_chat_ids():
            policy_on = await _policy_enabled(chat_id)
            groups = await self.db.find_exact_dup_groups(chat_id, now)
            if policy_on:
                for group in groups:
                    ids = sorted({int(row["id"]) for row in group})
                    # Обе строки живы; проигравший помечается superseded и
                    # получает указатель победителя (C-3 §3.3/§3.4.1.1 п.3/п.6).
                    keep = max(group, key=lambda r: (r["weight"], r["id"]))
                    losers = [int(row["id"]) for row in group
                              if row["id"] != keep["id"]
                              and not await self.db.is_fact_protected(
                                  chat_id, row["fact"])]
                    if losers:
                        await self._link_backward_supersede(
                            chat_id, int(keep["id"]),
                            [int(keep["id"]), *losers], now,
                            verification="verified")
                    for a_idx in range(len(ids)):
                        for b_idx in range(a_idx + 1, len(ids)):
                            pair = (ids[a_idx], ids[b_idx])
                            if pair in emitted:
                                continue
                            emitted.add(pair)
                            _emit_dedupe_candidate(
                                chat_id, "exact_duplicate", list(pair))
                            candidates += 1
            else:
                skipped_dedupe += len(groups)
            if self.memory._vec_available:
                # OFF: тот же проход считает пары и пишет honest skip — без
                # записей и удалений (F4: разбор пары обязан быть корректным
                # при любом значении гейта).
                candidates += await self._glue_vec_dups(
                    chat_id, now, policy_on=policy_on, emitted=emitted)
        if skipped_dedupe:
            logger.info(
                "graph review: dedupe skipped | reason=gate_off "
                "(no writes, no deletions) | exact_groups=%d", skipped_dedupe)
        expired = await self.db.purge_expired_graph_facts()
        unconfirmed = await self.db.purge_unconfirmed_graph_facts(
            now, hot.get("limits.graph_unconfirmed_retention_days", settings.GRAPH_UNCONFIRMED_RETENTION_DAYS))
        trimmed = await self.db.trim_compression_log(
            time.time(), hot.get("limits.graph_compression_log_retention_days", settings.GRAPH_COMPRESSION_LOG_RETENTION_DAYS))
        logger.info(
            "graph review: decision=%s dedupe_candidates=%d expired=%d "
            "unconfirmed=%d log_trimmed=%d",
            DECISION_NOOP, candidates, expired, unconfirmed, trimmed)

    async def _glue_vec_dups(self, chat_id: int, now: int, *,
                             policy_on: bool = False,
                             emitted: set | None = None) -> int:
        """66.11 → MEM-04.4: vec-кластеры cosine ≥0.95.

        ON — только КАНДИДАТ на дедуп (событие с id пары, не более одного раза
        на пару за прогон через `emitted`), без склейки и без удаления:
        сходство вектора не доказательство. OFF — ИНЕРТНО: пары считаются
        (диагностика), но ни записи, ни удаления, ни события (один honest
        skip-код). Потолок _REVIEW_VEC_BATCH фактов чата; защищённые не
        рассматриваются. Возврат — число пар-кандидатов (ON) либо 0 (OFF)."""
        rows = await self.db.get_live_graph_facts(chat_id, now)
        rows = [
            row for row in rows[: _REVIEW_VEC_BATCH]
            if not await self.db.is_fact_protected(chat_id, row["fact"])
        ]
        if len(rows) < 2:
            return 0
        try:
            vectors = await self.memory._embed([row["fact"] for row in rows])
        except Exception:
            logger.warning("graph review: vec glue embed failed — skipped")
            return 0
        by_id = {row["id"]: row for row in rows}
        pairs: dict[tuple, float] = {}
        for i, row in enumerate(rows):
            near = await self.memory._dedup_knn(chat_id, vectors[i])
            for item in near[: _MERGE_KNN_K]:
                other = by_id.get(item["fact_id"])
                if other is None or other["id"] == row["id"]:
                    continue
                cosine = 1.0 - item["distance"]
                if cosine >= _REVIEW_GLUE_SIM:
                    key = tuple(sorted((row["id"], other["id"])))
                    pairs[key] = max(pairs.get(key, 0.0), cosine)
        seen = emitted if emitted is not None else set()
        count = 0
        skipped_ids: set[int] = set()
        for (a_id, b_id), cosine in sorted(pairs.items()):
            if not policy_on:
                # Инертно: id пары читаются (F4 — форма данных проверяется
                # при любом значении гейта), но ни записи, ни удаления, ни
                # события не создаются.
                skipped_ids.update((int(a_id), int(b_id)))
                continue
            pair = tuple(sorted((int(a_id), int(b_id))))
            if pair in seen:
                continue
            seen.add(pair)
            _emit_dedupe_candidate(
                chat_id, "vector_similar", list(pair), similarity=cosine)
            count += 1
        if not policy_on and skipped_ids:
            logger.info(
                "graph review: vec dedupe skipped | reason=gate_off "
                "(no writes, no deletions) | chat_id=%s | ids=%d",
                chat_id, len(skipped_ids))
        return count

    async def shutdown(self) -> None:
        global _active_service
        if _active_service is self:
            _active_service = None
        try:
            if self._scheduler.running:
                self._scheduler.shutdown(wait=False)
                await asyncio.sleep(0)
            logger.info("MemoryMaintenance stopped")
        except SchedulerNotRunningError:
            logger.info("MemoryMaintenance was not running — nothing to stop")


# ── F7 (10.19, ADR-1019-6 D1/D1a/D2): retention импортированной истории ─────

_ARCHIVE_BATCH = 2000          # строк на пачку при экспорте архива
_ARCHIVE_PREFIX = "imported_history_"
# ⛔ IMMUTABLE (F9/ADR-1024-2 D2; owner UPD3 №5): файлы `imported_history_*.
# jsonl` содержат СЫРУЮ ИСТОРИЮ сообщений и НЕ являются кандидатами на
# удаление. Их не трогает ни retention диска (`services.disk_retention`:
# IMMUTABLE_PATTERNS/deny-list), ни какие-либо другие пути. Техдолг S10.19-24
# (ротация этих архивов) закрыт как Won't Fix — история хранится бессрочно.
IMMUTABLE_ARCHIVE_GLOB = "imported_history_*.jsonl"


def _flush_and_fsync(fh) -> None:
    """D-2.2 (Medium, ревью итерации 4): сбросить пользовательский буфер и
    форсировать `os.fsync` — архив ДОЛЖЕН пережить сбой питания РАНЬШЕ, чем
    SQLite-DELETE (иначе архив мог остаться только в page-cache, а DELETE
    персистироваться — необратимая потеря). Синхронно, вызывается через
    `asyncio.to_thread`, чтобы не блокировать event loop."""
    fh.flush()
    os.fsync(fh.fileno())


def _fsync_directory(directory) -> None:
    """S10.19-23 (ADR-1020-5 п.5, T-1910b): fsync КАТАЛОГА архива после
    fsync файла — только так запись ИМЕНИ нового файла в каталоге переживёт
    краш (POSIX). Best-effort: любые OSError → честный WARNING, прогон НЕ
    падает. На Windows (dev-платформа win32) каталог открыть нельзя —
    явный no-op с честным логом (R17: без путей/значений)."""
    if os.name == "nt":
        logger.info("[retention] dir fsync skipped (no-op on %s)", os.name)
        return
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    try:
        fd = os.open(str(directory), flags)
    except OSError as exc:
        logger.warning("[retention] dir fsync unavailable | reason=%s",
                       type(exc).__name__)
        return
    try:
        os.fsync(fd)
    except OSError as exc:
        logger.warning("[retention] dir fsync failed | reason=%s",
                       type(exc).__name__)
    finally:
        os.close(fd)


def _flush_fsync_and_dir(fh, directory) -> None:
    """D-2.2 + S10.19-23: fsync файла, затем каталога — одним
    `asyncio.to_thread`-вызовом (event loop не блокируется)."""
    _flush_and_fsync(fh)
    _fsync_directory(directory)


def auto_purge_dry_run(*, dry_run: bool, backup_confirmed: bool) -> bool:
    """Гейт деструктивного авто-крона (UPD4 п.3, D-2 High).

    Авто-крон (`summary_memory.compress_and_purge`) НЕ имеет права выполнять
    DELETE, пока оператор ЯВНО не включил apply (`dry_run=False`) **И** не
    подтвердил созданный/проверенный бэкап БД (`backup_confirmed=True`).
    Иначе — только dry-run (подсчёт) + WARNING на вызывающем. Единая точка
    правды для тестов (Δ каталога не растёт — env-флаги ClassVar)."""
    return bool(dry_run) or not bool(backup_confirmed)


async def _archive_imported_history(db, chat_cutoffs: dict[int, int],
                                    directory: Path
                                    ) -> tuple[bool, int, str, dict[int, int]]:
    """D2: экспорт выборки purge в файл ДО удаления (fail-safe).

    `{directory}/imported_history_<ts>.jsonl` — по строке JSON на запись
    (UTF-8). Возвращает `(ok, archived_rows, path, max_ids)`; любая ошибка
    записи → `ok=False` (вызывающий НЕ удаляет строки). Стриминг батчами —
    память ограничена `_ARCHIVE_BATCH`. R17-safe: файл содержит текст
    переписки, но сами логи пишут только число/путь без токенов.

    D-7 (ревью Батча E): `max_ids[chat_id]` — максимальный id, реально
    попавший в архив для чата. Purge ограничивается `id <= max_ids[chat_id]`
    (строго по зафиксированному множеству)."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("[retention] archive dir unavailable | reason=%s",
                       type(exc).__name__)
        return False, 0, "", {}
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    target = directory / f"{_ARCHIVE_PREFIX}{stamp}.jsonl"
    archived = 0
    max_ids: dict[int, int] = {int(c): 0 for c in chat_cutoffs}
    try:
        with open(target, "w", encoding="utf-8") as fh:
            for chat_id, cutoff in chat_cutoffs.items():
                after_id = 0
                while True:
                    rows = await db.select_imported_history(
                        int(chat_id), int(cutoff), after_id=after_id,
                        limit=_ARCHIVE_BATCH)
                    if not rows:
                        break
                    for row in rows:
                        fh.write(json.dumps(dict(row), ensure_ascii=False,
                                            default=str))
                        fh.write("\n")
                    archived += len(rows)
                    after_id = int(rows[-1]["id"])
                    max_ids[int(chat_id)] = after_id
                    if len(rows) < _ARCHIVE_BATCH:
                        break
            # D-2.2 + S10.19-23: fsync файла, затем КАТАЛОГА (имя файла
            # тоже должно пережить краш) — одним to_thread.
            await asyncio.to_thread(_flush_fsync_and_dir, fh, directory)
    except Exception:
        logger.warning("[retention] archive failed — purge skipped "
                       "(fail-safe)", exc_info=True)
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        return False, 0, str(target), {}
    return True, archived, str(target), max_ids


async def run_import_retention(db, *, dry_run: bool = False,
                               archive_dir: str | Path | None = None,
                               batch: int = 2000,
                               now: int | None = None) -> dict:
    """F7 (ADR-1019-6 D1/D1a/D2): ЕДИНСТВЕННЫЙ call-site purge импорта.

    Маппинг `chat_cutoffs` строится ТОЛЬКО из чатов, разрешённых
    `retention_policy.imported_history_purge_allowed` (чаты с retention `0=вечно` сюда не
    попадает никогда — структурный guard; дополнительно hard-deny по
    `enforce`-данным сида). `dry_run=True` → подсчёт без удаления. Иначе —
    обязательный архив в файл (`D2`, fail-safe: сбой архивации ⇒ строки не
    удаляются), затем батчевый purge.

    D-1 (Critical, ревью Батча E): если chat-слой НЕ читается (любой чат
    отдал `source='error'`) — прогон ОТМЕНЯЕТСЯ ЦЕЛИКОМ
    (`reason='chat_layer_unavailable'`), `chat_cutoffs` из fail-open
    `'default'` не строится.

    D-7: purge идёт строго по зафиксированному множеству (`id <= max_id` из
    архива); при расхождении `candidates != archived` (строки стали
    `history_processed=1` между снапшотом и удалением) — purge прерывается
    с WARNING без удаления.

    Возвращает `{chats, candidates, archived, deleted, batches, dry_run,
    reason, archive}`. Fail-open: ошибки БД → нули (не 500)."""
    now = int(time.time()) if now is None else int(now)
    out = {"chats": 0, "candidates": 0, "archived": 0, "deleted": 0,
           "batches": 0, "dry_run": bool(dry_run), "reason": "ok",
           "archive": ""}
    try:
        chat_ids = await db.get_smart_chat_ids()
    except Exception:
        logger.warning("[retention] chat list failed — fail-open",
                       exc_info=True)
        out["reason"] = "chat_list_failed"
        return out
    chat_cutoffs: dict[int, int] = {}
    layer_error = False
    for chat_id in chat_ids:
        try:
            allowed, days, source = \
                await retention_policy.imported_history_purge_allowed(chat_id)
        except Exception:
            allowed, days, source = False, 0, "error"
        if source == "error":
            # D-1: chat-слой недоступен → НЕ доверяем fail-open дефолту.
            layer_error = True
            logger.warning(
                "[retention] chat layer unavailable — run aborted "
                "(fail-closed) | chat=%s", chat_id)
            continue
        if not allowed:
            # R17: только id/источник; чаты с retention 0 (вечно) сюда попадают.
            logger.info("[retention] import purge skip | chat=%s | "
                        "reason=eternal | source=%s", chat_id, source)
            continue
        chat_cutoffs[int(chat_id)] = now - int(days) * 86400
    if layer_error:
        out["reason"] = "chat_layer_unavailable"
        return out
    if not chat_cutoffs:
        out["reason"] = "no_candidates"
        return out
    out["chats"] = len(chat_cutoffs)
    # Сначала ВСЕГДА подсчёт (dry-run-семантика): нет кандидатов — не трогаем
    # архив/диск (дешёвый выход).
    try:
        probe = await db.purge_imported_history(
            chat_cutoffs=chat_cutoffs, batch=batch, dry_run=True)
        out["candidates"] = int(probe.get("candidates") or 0)
    except Exception:
        logger.warning("[retention] candidate count failed — skip",
                       exc_info=True)
        out["reason"] = "count_failed"
        return out
    if out["candidates"] == 0:
        out["reason"] = "no_candidates"
        return out
    if dry_run:
        out["reason"] = "dry_run"
        logger.info("[retention] import dry-run | chats=%d candidates=%d",
                    len(chat_cutoffs), out["candidates"])
        return out
    directory = Path(archive_dir or hot.get(
        "reactions.memory_backup_dir", settings.MEMORY_BACKUP_DIR))
    ok, archived, path, max_ids = await _archive_imported_history(
        db, chat_cutoffs, directory)
    if not ok:
        out["reason"] = "archive_failed"
        return out
    out["archived"] = archived
    out["archive"] = path
    # D-7: сверяем «кандидаты по зафиксированным id» с архивом — расхождение
    # означает гонку с history_processed → НЕ удаляем.
    try:
        fixed = await db.purge_imported_history(
            chat_cutoffs=chat_cutoffs, batch=batch, dry_run=True,
            chat_max_ids=max_ids)
        fixed_candidates = int(fixed.get("candidates") or 0)
    except Exception:
        logger.warning("[retention] fixed-count failed — purge skipped",
                       exc_info=True)
        out["reason"] = "count_failed"
        return out
    out["candidates"] = fixed_candidates
    if fixed_candidates != archived:
        logger.warning(
            "[retention] archive/purge mismatch — purge aborted | "
            "archived=%d candidates=%d", archived, fixed_candidates)
        out["reason"] = "archive_mismatch"
        return out
    res = await db.purge_imported_history(
        chat_cutoffs=chat_cutoffs, batch=batch, dry_run=False,
        chat_max_ids=max_ids)
    out["candidates"] = int(res.get("candidates") or 0)
    out["deleted"] = int(res.get("deleted") or 0)
    out["batches"] = int(res.get("batches") or 0)
    logger.info(
        "[retention] import purge | chats=%d archived=%d deleted=%d "
        "batches=%d", out["chats"], out["archived"], out["deleted"],
        out["batches"])
    return out


# ── F4 (paradigm-thresholds-consolidation-round1021, ADR-1021-4) ──────────
# READ-ONLY аудит причин пустого мета-слоя + идемпотентная Memory
# Consolidation. Консолидация — ТОЛЬКО ручной CLI-вызов (`manage.py memory
# consolidate`), авто-крона нет. Дефолт — боевой прогон; `--dry-run` — опция.

_DREAM_LOG_KINDS = ("run", "distilled", "skipped", "error",
                    "deep_run", "deep_skip", "deep_traits")


async def collect_paradigm_audit(db) -> dict:
    """READ-ONLY аудит T-1972: где обрыв цепочки «сон → глубокий сон →
    парадигмы».

    Возвращает фактические значения флагов, счётчики `memory_dream_log` по
    kind, число парадигм/убеждений и определённую «точку обрыва» с ветвью
    spec §3.3 (A — флаги, B — пороги, C — кап). Только bounded SELECT;
    никаких мутаций. R17: счётчики и bool-флаги, без текстов."""
    out = {
        "flags": {},
        "dream_log": {},
        "last_run": {},
        "paradigms_total": 0,
        "paradigms_by_chat": {},
        "beliefs_by_status": {},
        "break_point": "unknown",
        "branch": "unknown",
    }
    from services.worker_settings import resolve_setting_cached

    flag_specs = (
        ("dream_enabled", "memory.dream_enabled", settings.DREAM_ENABLED),
        ("deep_sleep_enabled", "flags.deep_sleep_enabled",
         settings.DEEP_SLEEP_ENABLED),
        ("belief_decay_enabled", "flags.belief_decay_enabled",
         settings.BELIEF_DECAY_ENABLED),
    )
    for label, key, default in flag_specs:
        try:
            value = bool(await resolve_setting_cached(key, default=default))
        except Exception:
            value = bool(default)
        out["flags"][label] = value

    for kind in _DREAM_LOG_KINDS:
        try:
            cursor = await db.db.execute(
                "SELECT COUNT(*) AS c FROM memory_dream_log WHERE kind = ?",
                (kind,))
            row = await cursor.fetchone()
            out["dream_log"][kind] = int(row["c"]) if row else 0
        except Exception:
            out["dream_log"][kind] = 0
    for label, kinds in (("deep_run", ("deep_run",)),
                         ("deep_skip", ("deep_skip",))):
        try:
            ts = await db.last_run_at(kinds)
        except Exception:
            ts = None
        out["last_run"][label] = ts

    try:
        out["paradigms_total"] = int(await db.count_paradigms())
    except Exception:
        out["paradigms_total"] = 0
    try:
        cursor = await db.db.execute(
            "SELECT chat_id, COUNT(*) AS c FROM graph_facts "
            "WHERE kind = 'belief' AND (belief_meta LIKE ? OR "
            "belief_meta LIKE ?) GROUP BY chat_id",
            ('%"type":"paradigm"%', '%"type": "paradigm"%'))
        out["paradigms_by_chat"] = {
            int(r["chat_id"]): int(r["c"]) for r in await cursor.fetchall()}
    except Exception:
        out["paradigms_by_chat"] = {}
    try:
        out["beliefs_by_status"] = await db.count_beliefs_by_status()
    except Exception:
        out["beliefs_by_status"] = {}

    # Точка обрыва (spec §2.2/§3.3): цепочка гейтов.
    flags = out["flags"]
    log = out["dream_log"]
    ordinary = int(log.get("run", 0)) + int(log.get("distilled", 0)) + \
        int(log.get("skipped", 0)) + int(log.get("error", 0))
    deep_attempts = int(log.get("deep_run", 0)) + int(log.get("deep_skip", 0))
    if not flags.get("dream_enabled") and not flags.get("deep_sleep_enabled"):
        out["break_point"], out["branch"] = "flags_off", "A"
    elif ordinary == 0:
        out["break_point"], out["branch"] = "no_dream_runs", "A"
    elif deep_attempts == 0:
        # Обычный сон шёл, но глубокий не запускался — триггер/флаг.
        out["break_point"], out["branch"] = "no_deep_runs", "A"
    elif out["paradigms_total"] == 0:
        out["break_point"], out["branch"] = "no_paradigms", "B"
    else:
        out["break_point"], out["branch"] = "ok", "none"
    return out


def _belief_source_ids(raw) -> list[int]:
    """`source_ids` убеждения (JSON-массив) → список int (мусор пропускаем)."""
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    ids: list[int] = []
    for item in data:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


async def consolidate(db, *, chat_ids=None, dry_run: bool = False,
                      limit: int = 200, min_sources: int = 2,
                      now: int | None = None, db_path=None,
                      backup_dir=None, allow_no_backup: bool = False) -> dict:
    """F4/§3.2: идемпотентная Memory Consolidation (сжатие убеждений в
    парадигмы).

    Вход — bounded-выборка убеждений чата (`belief_meta.type='belief'`),
    ранжирование по числу опор (`source_ids`). Выход — парадигмы через
    `DreamWorker._write_paradigm` с дедупом `_paradigm_dedup_keys` /
    `_deep_dedup_key`. Капы не снимаются (S10.21-1): на чат пишется не больше
    `limits.deep_sleep_max_paradigms_per_run` (иначе
    `DEEP_SLEEP_MAX_PARADIGMS`) парадигм за прогон, а выборка ограничена
    `limits.deep_sleep_top_k` (`DEEP_SLEEP_TOP_K`) — как в Deep Sleep-пасе.
    Повторный прогон — 0 записей (идемпотентность). Вызывается
    ТОЛЬКО из CLI (F5), авто-крона нет; `dry_run` ничего не пишет.

    F4 fix-round 10.21 (R1): при боевом прогоне с `db_path` — авто-бэкап ДО
    первой записи + JSONL-архив ЗАПИСЫВАЕМЫХ парадигм (страховка/откат, по
    образцу F5). `db_path`/`backup_dir` прокидывает CLI (`manage.py memory
    consolidate`).

    F4 fix-round 2 (Medium): страховка **fail-closed** — боевой прогон без
    `db_path` НЕ пишет (reason `backup_unavailable`, выход до первой записи),
    как в F5. Явный opt-in `allow_no_backup=True` возвращает прежнее
    «пишем без страховки» поведение; в прод-коде он не выставляется.

    Возврат: `{chats, scanned, candidates, written, skipped, reasons,
    archived, backup, dry_run}`."""
    from services.dream_worker import DreamWorker, _deep_dedup_key

    out = {"dry_run": bool(dry_run), "chats": 0, "scanned": 0,
           "candidates": 0, "written": 0, "skipped": 0, "reasons": {},
           "archived": 0, "backup": "", "max_paradigms": 0}

    def _reason(code: str) -> None:
        out["reasons"][code] = out["reasons"].get(code, 0) + 1

    # S10.21-1: те же капы, что у Deep Sleep-паса (`dream_worker.py`):
    # per-chat не больше MAX_PARADIGMS, выборка не шире TOP_K. Каталог/схема
    # не меняются — значения лишь читаются.
    def _cap(key: str, default) -> int:
        try:
            return max(1, int(hot.get(key, default)))
        except (TypeError, ValueError):
            return max(1, int(default))

    max_paradigms = _cap("limits.deep_sleep_max_paradigms_per_run",
                         settings.DEEP_SLEEP_MAX_PARADIGMS)
    read_cap = _cap("limits.deep_sleep_top_k", settings.DEEP_SLEEP_TOP_K)
    out["max_paradigms"] = max_paradigms
    read_limit = min(max(1, int(limit)), read_cap)
    now = int(time.time()) if now is None else int(now)
    if chat_ids is None:
        try:
            chat_ids = await db.get_graph_chat_ids()
        except Exception:
            logger.warning("[consolidate] chat list failed — fail-open",
                           exc_info=True)
            chat_ids = []
    worker = DreamWorker(db, memory=None, llm=None)
    # Пасс 1: собрать кандидатов (дедуп внутри прогона — по ключу).
    candidates: list[dict] = []
    for chat_id in chat_ids:
        out["chats"] += 1
        try:
            rows = await db.list_recent_beliefs(
                chat_id=chat_id, limit=read_limit, status="confirmed",
                belief_type="belief")
        except Exception:
            logger.warning("[consolidate] belief read failed | chat=%s",
                           chat_id, exc_info=True)
            _reason("read_error")
            out["skipped"] += 1
            continue
        out["scanned"] += len(rows)
        try:
            existing = await worker._paradigm_dedup_keys(chat_id)
        except Exception:
            existing = set()
        ranked = sorted(
            rows, key=lambda r: len(_belief_source_ids(r.get("source_ids"))),
            reverse=True)
        per_chat = 0
        for row in ranked:
            if per_chat >= max_paradigms:
                # S10.21-1: не снимаем кап MAX_PARADIGMS за один прогон.
                _reason("cap_reached")
                out["skipped"] += 1
                continue
            ids = _belief_source_ids(row.get("source_ids"))
            text = " ".join(str(row.get("fact") or "").split())
            if not text:
                _reason("empty_text")
                out["skipped"] += 1
                continue
            if len(ids) < max(1, int(min_sources)):
                _reason("below_min_sources")
                out["skipped"] += 1
                continue
            anchors = [{"fact": text, "target_user": row.get("target_user")}]
            key = _deep_dedup_key(text, anchors)
            if key in existing:
                _reason("duplicate")
                out["skipped"] += 1
                continue
            out["candidates"] += 1
            per_chat += 1
            existing.add(key)
            if dry_run:
                continue
            candidates.append({
                "chat_id": int(chat_id),
                "fact": text,
                "target_user": row.get("target_user"),
                "source_ids": row.get("source_ids"),
                "anchors": anchors,
                "key": key,
                "ids": ids,
            })
    # Страховочная сетка ДО первой записи (боевой прогон с db_path).
    if not dry_run and candidates:
        if not db_path:
            # F4 fix-round 2 (Medium): fail-closed — без пути к БД страховку
            # создать нельзя, поэтому НЕ пишем (F5-семантика). Явный opt-in
            # allow_no_backup=True оставляет прежнее поведение (тесты/утилиты).
            if not allow_no_backup:
                _reason("backup_unavailable")
                return out
            out["backup"] = ""
        else:
            # Ленивый импорт: memory_rebuild импортирует
            # `_flush_fsync_and_dir` из этого модуля (циклический импорт).
            from services.memory_rebuild import (
                _safety_backup, _archive_generated_rows,
                _resolve_backup_dir)
            ok, backup_path, reason = await _safety_backup(
                db_path, backup_dir, "consolidate")
            if not ok:
                _reason(reason)
                return out
            out["backup"] = backup_path
            ok, archived, _path = await _archive_generated_rows(
                candidates, _resolve_backup_dir(backup_dir), "consolidate")
            if not ok or archived != len(candidates):
                _reason("archive_mismatch")
                out["skipped"] += len(candidates)
                return out
            out["archived"] = archived
    # Пасс 2: запись парадигм.
    for cand in candidates:
        try:
            fact_id = await worker._write_paradigm(
                cand["chat_id"], cand["fact"], {}, cand["anchors"],
                cand["ids"], cand["key"], now)
        except Exception:
            logger.warning("[consolidate] paradigm write failed | chat=%s",
                           cand["chat_id"], exc_info=True)
            fact_id = None
        if fact_id:
            out["written"] += 1
        else:
            _reason("write_failed")
            out["skipped"] += 1
    if out["written"] or out["candidates"]:
        logger.info(
            "[consolidate] scanned=%d candidates=%d written=%d skipped=%d "
            "archived=%d dry_run=%s", out["scanned"], out["candidates"],
            out["written"], out["skipped"], out["archived"], out["dry_run"])
    return out
