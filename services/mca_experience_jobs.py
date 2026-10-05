"""MCA-16 `mca-16-experience-lessons` — пакетный review опыта (ADR-1028-15 D7).

Единственный новый тип durable-job в СУЩЕСТВУЮЩЕЙ очереди (mca-01, §95):
``kind="experience.review"``, ``owner="mca16"``,
``coalesce_key="experience.review:global"`` (singleflight; прецедент
``mca_episode_jobs.py``). Второй очереди/планировщика нет.

Триггеры (spec §7): каденция ``memory.experience_review_cadence``
(hourly/daily/weekly; default daily) из существующего расписания обслуживания
(``MemoryMaintenanceService``) + немедленный enqueue при содержательной
коррекции (``enqueue_on_correction``; owner/participant).

Шаги одного запуска (bounded batch ``MCA_EXPERIENCE_REVIEW_BATCH_MAX``):
capture-cursor → propose → validate → activate/suspend → outcome-link →
utility-update → recheck → prune (retention). Checkpoint/counters — durable
``task_jobs`` payload; повторный запуск идемпотентен (UNIQUE-ключи v28).

Инварианты:
* **На каждое сообщение LLM-рефлексии НЕТ**: предложения — детерминированные
  канонические правила (``CANONICAL_RECOMMENDATIONS``); модуль не импортирует
  LLM-клиент и не делает ни одного внешнего вызова.
* **Случайность** — только существующая политика 14.5/mca-10a: журнал
  ``mca_random_draws`` читается read-only как наблюдение
  (``recent_draw_observations``); второй RandomSource/процент экспериментов
  не создаётся; истинность/успех урока не рандомизируются (в модуле нет
  ГПСЧ и вероятностных констант).
* **Захват** — только из типизированных durable-источников: feedback
  (``mca_experience_feedback``) и notable-терминалы инструментов
  (``mca_events.tool_call``, mca-11). Каждый ingest идемпотентен.
* **Исход линкуется** к реально применённому уроку только по независимому
  типизированному событию и только позже применения (application_ref/trace);
  ``unknown`` не обновляет success/failure (без ложной награды).
* **Deep sleep не смешивает lessons с парадигмами**: отдельный kind job,
  отдельные таблицы; пайплайн mca-06 не трогается (R6b).
* R17: только ID/коды/числа/enum/ссылки; сырой текст/секреты не журналятся.
* OFF (K1/K3): job не запускается (честный ``disabled``); события — через
  единственный ``emit_mca_event`` (mca-13).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from services import mca_gates
from services import mca_experience as me
from services.task_supervisor import (
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_QUEUED,
    JOB_RUNNING,
    TaskJobStore,
)

logger = logging.getLogger(__name__)

REVIEW_JOB_KIND = "experience.review"
REVIEW_OWNER = "mca16"
REVIEW_COALESCE_KEY = "experience.review:global"

#: Каденция → секунды (значения каталога; hot-чтение per-tick — без рестарта).
CADENCE_SECONDS = {"hourly": 3600, "daily": 86400, "weekly": 604800}
DEFAULT_CADENCE = "daily"

#: feedback source_kind → (outcome_kind, outcome_source) эпизода. Коррекция
#: владельца/участника — проверяемое свидетельство неудачи прошлого ответа;
#: social/LLM — не ground truth (unknown); technical — только своя стадия.
_FEEDBACK_OUTCOME = {
    "owner_correction": ("failure", "explicit"),
    "participant_correction": ("failure", "explicit"),
    "social_reaction": ("unknown", "social"),
    "llm_hypothesis": ("unknown", "llm_hypothesis"),
    "technical": ("unknown", "technical"),
}

#: Измерение полезности по типу урока (закрытый набор mca-16).
_MEASUREMENT_BY_TYPE = {
    "tool_usage": "tool_success",
    "retrieval": "correctness",
    "context": "contextual_fit",
    "social_preference": "preference_fit",
    "failure_pattern": "correctness",
}

#: Детерминированные правила предложения (canonical rule_key; без LLM).
PROPOSAL_RULE_TOOL_FAILURES = ("tool_usage", "retry_after_typed_failure")
PROPOSAL_RULE_CORRECTIONS = ("failure_pattern", "reproduce_before_fix")
PROPOSAL_RULE_PREFERENCE = ("social_preference", "explicit_user_preference")

_PRUNE_BATCH = 5000              # bounded-удаление за шаг (GEN-R8)


def review_coalesce_key() -> str:
    """Unique key durable-задачи (singleflight; без параллельного запуска)."""
    return REVIEW_COALESCE_KEY


def default_counters() -> dict:
    """Счётчики job (checkpoint-payload; честные — не подменяются)."""
    return {
        "captured_feedback": 0, "captured_events": 0, "proposed": 0,
        "skipped_existing": 0, "validated": 0, "activated": 0,
        "suspended": 0, "outcomes_linked": 0, "utility_updates": 0,
        "stale_marked": 0, "pruned_episodes": 0, "pruned_feedback": 0,
        "pruned_applications": 0, "errors": 0, "batches": 0,
    }


def review_status_from_job(row: dict | None) -> str | None:
    """Статус durable-задачи review (для витрины/диагностики)."""
    if row is None:
        return None
    return str(row.get("status") or "")


def _learning_enabled() -> bool:
    """UI-настройка `memory.experience_learning_enabled` (hot; default true).

    Это НЕ kill-switch: K1/K3 — env-only гейты (spec D11); настройка лишь
    останавливает НОВОЕ обучение (review), не удаляя уже выученное."""
    try:
        from services import hot_config as hot
        from config.settings import settings
        return bool(hot.get(
            "memory.experience_learning_enabled",
            getattr(settings, "EXPERIENCE_LEARNING_ENABLED", True)))
    except Exception:
        return True


def review_cadence() -> str:
    """Каденция из существующих настроек (hot; применяется без рестарта)."""
    try:
        from services import hot_config as hot
        from config.settings import settings
        value = str(hot.get(
            "memory.experience_review_cadence",
            getattr(settings, "EXPERIENCE_REVIEW_CADENCE",
                    DEFAULT_CADENCE)) or DEFAULT_CADENCE)
    except Exception:
        value = DEFAULT_CADENCE
    return value if value in CADENCE_SECONDS else DEFAULT_CADENCE


def review_enabled() -> bool:
    """K1 master + K3 review + UI-настройка learning enabled (fail-closed)."""
    try:
        if not (mca_gates.experience_lessons_enabled()
                and mca_gates.experience_review_enabled()):
            return False
    except Exception:
        return False
    return _learning_enabled()


async def enqueue_experience_review(db, *, max_attempts: int = 3
                                    ) -> str | None:
    """Поставить review в durable-очередь (coalescing: активный → его job_id).

    OFF (K1/K3/настройка) → None (job не создаётся; честный ``disabled``)."""
    if not review_enabled():
        return None
    store = TaskJobStore(db)
    payload = json.dumps({
        "cursor_feedback_rowid": 0,
        "cursor_event_rowid": 0,
        "counters": default_counters(),
    }, ensure_ascii=True)
    return await store.enqueue(
        owner=REVIEW_OWNER, kind=REVIEW_JOB_KIND,
        coalesce_key=REVIEW_COALESCE_KEY, payload=payload,
        max_attempts=max(1, int(max_attempts)))


async def enqueue_on_correction(db, *, source_kind: str) -> str | None:
    """Немедленный enqueue при СОДЕРЖАТЕЛЬНОЙ коррекции (spec §7).

    Только owner/participant-коррекции (social/LLM/technical — не триггер).
    Fail-open: ошибка очереди не рвёт поток записи feedback."""
    if str(source_kind) not in ("owner_correction", "participant_correction"):
        return None
    try:
        return await enqueue_experience_review(db)
    except Exception:
        logger.warning("[mca16] correction review enqueue failed — skip",
                       exc_info=True)
        return None


async def get_active_review(db) -> dict | None:
    """Активная (queued/running) review-задача или None (singleflight)."""
    cursor = await db.db.execute(
        "SELECT * FROM task_jobs WHERE coalesce_key = ? AND status IN (?, ?) "
        "ORDER BY created_at DESC LIMIT 1",
        (REVIEW_COALESCE_KEY, JOB_QUEUED, JOB_RUNNING))
    row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def last_completed_review_at(db) -> int | None:
    """Время последнего терминального review-прогона (для каденции)."""
    cursor = await db.db.execute(
        "SELECT MAX(finished_at) AS last FROM task_jobs "
        "WHERE kind = ? AND status IN (?, ?)",
        (REVIEW_JOB_KIND, JOB_COMPLETED, JOB_FAILED))
    row = await cursor.fetchone()
    if row is None or row["last"] is None:
        return None
    return int(row["last"])


async def tick_experience_review(db, *, now: int | None = None) -> str:
    """Один тик существующего расписания обслуживания (MemoryMaintenance).

    Приоритет: уже стоящая в очереди задача → выполнить; иначе — due по
    каденции → enqueue + выполнить. Возврат — статус job или ``disabled``/
    ``not_due``/``running`` (честные коды, без выдуманных успехов)."""
    if not review_enabled():
        return "disabled"
    now = int(time.time()) if now is None else int(now)
    try:
        active = await get_active_review(db)
    except Exception:
        logger.warning("[mca16] review queue read failed — skip tick",
                       exc_info=True)
        return "error"
    if active is not None:
        if str(active.get("status")) == JOB_RUNNING:
            return "running"                     # singleflight: не дублируем
        job_id = str(active.get("job_id") or "")
    else:
        interval = CADENCE_SECONDS[review_cadence()]
        try:
            last = await last_completed_review_at(db)
        except Exception:
            last = None
        if last is not None and (now - last) < interval:
            return "not_due"
        try:
            job_id = await enqueue_experience_review(db) or ""
        except Exception:
            logger.warning("[mca16] review enqueue failed", exc_info=True)
            return "error"
        if not job_id:
            return "disabled"
    return await ExperienceReviewRunner(db).run(job_id)


async def recent_draw_observations(db, *, limit: int = 20) -> list[dict]:
    """Read-only наблюдение журнала `mca_random_draws` (mca-10a, CA-16-3).

    Случайность разнообразит допустимые действия, но НЕ рандомизирует
    истинность/успех/оценку урока; второго RandomSource/процента нет.
    Возврат — bounded R17-safe строки (ID/коды/числа)."""
    try:
        cursor = await db.db.execute(
            "SELECT draw_id, created_at, chat_id, purpose, source, "
            "selected_id, fallback_reason FROM mca_random_draws "
            "ORDER BY created_at DESC LIMIT ?", (max(1, int(limit)),))
        return [dict(r) for r in await cursor.fetchall()]
    except Exception:
        return []


def _emit(event_name: str, *, outcome: str, reason_code: str | None = None,
          level: str | None = None, **fields) -> None:
    """Notable-событие через единственный `emit_mca_event` (R17-safe)."""
    try:
        from services import mca_events
        if level is None:
            level = (mca_events.LEVEL_WARN
                     if outcome in ("failed", "silent") else mca_events.LEVEL_INFO)
        mca_events.emit_mca_event(event_name, outcome=outcome, level=level,
                                  component="experience",
                                  reason_code=reason_code, **fields)
    except Exception:      # fail-open: событие не рвёт поток
        return


def _parse_json_list(raw) -> list:
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    return list(data) if isinstance(data, list) else []


def _parse_json_dict(raw) -> dict:
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _episode_event_ts(episode: dict) -> int:
    """Время НАБЛЮДЕНИЯ эпизода (trace/feedback), не время захвата.

    Эпизод фиксирует `event_ts` источника (mca_events.ts/feedback.ts) в
    `decision_json`; fallback — `created_at` (capture-время). Нужно для
    temporal holdout и проверки «исход позже применения»."""
    try:
        event_ts = _parse_json_dict(episode.get("decision_json")).get(
            "event_ts")
        if event_ts is not None:
            return int(event_ts)
    except (TypeError, ValueError):
        pass
    try:
        return int(episode.get("created_at") or 0)
    except (TypeError, ValueError):
        return 0


class ExperienceReviewRunner:
    """Исполнитель durable-задачи `experience.review` (реентерабельный).

    Никаких LLM/внешних вызовов; шаги bounded; ошибка шага → честный
    `failed` (никогда ложный `completed`); отмена → `interrupted`."""

    def __init__(self, db, *, cancel_cb=None) -> None:
        self._db = db
        self._store = TaskJobStore(db)
        self._service = me.get_service(db)
        self._cancel_cb = cancel_cb

    # ── payload/checkpoint (durable курсор) ───────────────────────────────

    async def _load_payload(self, job_id: str) -> dict:
        cursor = await self._db.db.execute(
            "SELECT payload FROM task_jobs WHERE job_id = ?", (job_id,))
        row = await cursor.fetchone()
        try:
            data = json.loads(row["payload"] or "{}") if row else {}
        except (ValueError, TypeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("cursor_feedback_rowid", 0)
        data.setdefault("cursor_event_rowid", 0)
        counters = data.setdefault("counters", default_counters())
        for key, value in default_counters().items():
            counters.setdefault(key, value)
        # Курсор durable ПОВЕРХ job-строки: новый запуск наследует позицию
        # последнего терминального review-прогона (идемпотентный повтор
        # событий не сканируется заново; bounded-порции продолжаются).
        if not int(data.get("cursor_feedback_rowid") or 0) \
                and not int(data.get("cursor_event_rowid") or 0):
            await self._inherit_cursor(data)
        return data

    async def _inherit_cursor(self, data: dict) -> None:
        try:
            cursor = await self._db.db.execute(
                "SELECT payload FROM task_jobs WHERE kind = ? AND status IN "
                "('completed','failed') "
                "ORDER BY finished_at DESC, created_at DESC LIMIT 1",
                (REVIEW_JOB_KIND,))
            row = await cursor.fetchone()
            if row is None:
                return
            prev = json.loads(row["payload"] or "{}")
            if not isinstance(prev, dict):
                return
            data["cursor_feedback_rowid"] = max(
                int(data.get("cursor_feedback_rowid") or 0),
                int(prev.get("cursor_feedback_rowid") or 0))
            data["cursor_event_rowid"] = max(
                int(data.get("cursor_event_rowid") or 0),
                int(prev.get("cursor_event_rowid") or 0))
        except Exception:
            logger.warning("[mca16] review cursor inherit failed — from zero",
                           exc_info=True)

    async def _checkpoint(self, job_id: str, payload: dict) -> None:
        payload_json = json.dumps(payload, ensure_ascii=True)
        now = int(time.time())

        async def _body(_conn):
            await self._db.db.execute(
                "UPDATE task_jobs SET payload = ?, progress_at = ?, "
                "updated_at = ? WHERE job_id = ?",
                (payload_json, now, now, job_id))
            return 1

        await self._db.write_transaction(_body, op_name="mca16_review_checkpoint")

    async def _finish(self, job_id: str, *, status: str, reason_code=None,
                      payload: dict | None = None) -> None:
        if payload is not None:
            await self._checkpoint(job_id, payload)
        await self._store.finish(job_id, status=status, reason_code=reason_code)

    # ── главный цикл ──────────────────────────────────────────────────────

    async def run(self, job_id: str) -> str:
        """Выполнить задачу до честного терминального статуса."""
        if not review_enabled():
            await self._finish(job_id, status=JOB_CANCELLED,
                               reason_code="cancelled")
            return JOB_CANCELLED
        payload = await self._load_payload(job_id)
        started = await self._store.mark_running(job_id)
        if not started:
            row = await self._store.get(job_id)
            return review_status_from_job(row) or JOB_RUNNING
        counters = payload["counters"]
        try:
            await self._store.heartbeat(job_id)
            counters["captured_feedback"] += await self._capture_feedback(
                payload)
            counters["captured_events"] += await self._capture_tool_events(
                payload)
            batch = await self._propose_batch()
            counters["proposed"] += int(batch.get("proposed") or 0)
            counters["skipped_existing"] += int(batch.get("skipped") or 0)
            outcome = await self._validate_and_activate(
                batch.get("candidates") or ())
            counters["validated"] += int(outcome.get("validated") or 0)
            counters["activated"] += int(outcome.get("activated") or 0)
            counters["suspended"] += await self._suspend_contradicted()
            counters["outcomes_linked"] += await self._link_outcomes()
            if counters["outcomes_linked"]:
                counters["utility_updates"] += 1
                _emit("utility_updated", outcome="success",
                      reason_code="utility_updated", job_id=job_id,
                      config_version=me.EXPERIENCE_POLICY_VERSION,
                      entity_ids=[str(x) for x in
                                  (batch.get("linked_lesson_ids") or ())][:20])
            counters["stale_marked"] += await self._recheck_stale()
            pruned = await self._prune()
            for key, value in pruned.items():
                counters[key] = int(counters.get(key) or 0) + int(value or 0)
            counters["batches"] += 1
            payload["counters"] = counters
            await self._finish(job_id, status=JOB_COMPLETED, payload=payload)
            return JOB_COMPLETED
        except asyncio.CancelledError:
            await self._finish(job_id, status="interrupted",
                               reason_code="cancelled", payload=payload)
            raise
        except Exception:
            counters["errors"] = int(counters.get("errors") or 0) + 1
            payload["counters"] = counters
            logger.warning("[mca16] review job failed | job_id=%s", job_id,
                           exc_info=True)
            await self._finish(job_id, status=JOB_FAILED,
                               reason_code="task_failed", payload=payload)
            return JOB_FAILED

    # ── шаг 1: capture-cursor (дёшево, пакетно, идемпотентно) ─────────────

    async def _capture_feedback(self, payload: dict) -> int:
        """Новые active-feedback без эпизода → ExperienceEpisode (idempotent).

        K2 OFF: нетекнические сигналы не читаются/не обрабатываются (курсор
        всё равно продвигается — без цикла)."""
        limit = me.ExperiencePolicy.review_batch_max()
        cursor = await self._db.db.execute(
            "SELECT rowid AS rid, * FROM mca_experience_feedback "
            "WHERE status = 'active' AND episode_id IS NULL AND rowid > ? "
            "ORDER BY rowid LIMIT ?",
            (int(payload.get("cursor_feedback_rowid") or 0), limit))
        rows = [dict(r) for r in await cursor.fetchall()]
        captured = 0
        for row in rows:
            payload["cursor_feedback_rowid"] = int(row["rid"])
            source_kind = str(row.get("source_kind") or "")
            if source_kind not in _FEEDBACK_OUTCOME:
                continue
            if source_kind != "technical" \
                    and not mca_gates.experience_feedback_enabled():
                continue                       # K2 OFF: контур закрыт
            outcome_kind, outcome_source = _FEEDBACK_OUTCOME[source_kind]
            try:
                episode_id = await self._service.capture_episode(
                    scope="chat", chat_id=row.get("chat_id"),
                    task_type="feedback",
                    trace_id=row.get("trace_id"),
                    operation_id=row.get("operation_id"),
                    feedback_id=str(row.get("feedback_id")),
                    decision={"event_ts": int(row.get("ts") or 0)},
                    outcome_kind=outcome_kind,
                    outcome_source=outcome_source)
            except Exception:
                logger.warning("[mca16] feedback capture failed — skip",
                               exc_info=True)
                continue
            if episode_id:
                captured += 1
        return captured

    async def _capture_tool_events(self, payload: dict) -> int:
        """Notable-терминалы `tool_call` (mca-11) → эпизоды-неудачи.

        Только `outcome='failed'` (error/timeout): типизированный технический
        исход своей стадии. Каждое событие — отдельный primary event
        (`operation_id="mca_event:<id>"`), повторный ingest → no-op."""
        limit = me.ExperiencePolicy.review_batch_max()
        cursor = await self._db.db.execute(
            "SELECT id, ts, event_name, outcome, chat_id, trace_id, "
            "entity_ids, reason_code FROM mca_events WHERE id > ? "
            "AND event_name = 'tool_call' ORDER BY id LIMIT ?",
            (int(payload.get("cursor_event_rowid") or 0), limit))
        rows = [dict(r) for r in await cursor.fetchall()]
        captured = 0
        for row in rows:
            payload["cursor_event_rowid"] = int(row["id"])
            if str(row.get("outcome")) != "failed":
                continue                       # cancelled/denied ≠ неудача
            entity = _parse_json_dict(row.get("entity_ids"))
            tool = str(entity.get("tool") or "")
            if not tool:
                continue
            try:
                episode_id = await self._service.capture_episode(
                    scope="chat", chat_id=row.get("chat_id"),
                    task_type="tool_chain", trace_id=row.get("trace_id"),
                    operation_id=f"mca_event:{int(row['id'])}",
                    tool_ids=[tool],
                    decision={"reason_code": str(row.get("reason_code") or ""),
                              "status": "failed",
                              "event_ts": int(row.get("ts") or 0)},
                    outcome_kind="failure", outcome_source="technical")
            except Exception:
                logger.warning("[mca16] tool event capture failed — skip",
                               exc_info=True)
                continue
            if episode_id:
                captured += 1
        return captured

    # ── шаг 2: propose (детерминированные канонические правила) ──────────

    async def _propose_batch(self) -> dict:
        """Кандидаты из повторяющихся типизированных наблюдений (без LLM).

        Дедуп: открытый (не superseded) урок с тем же каноном/scope → skip
        (повторный запуск не плодит дубликаты)."""
        limit = me.ExperiencePolicy.review_batch_max()
        need = me.ExperiencePolicy.min_independent_episodes()
        candidates: list[dict] = []
        skipped = 0

        # P1: ≥need независимых технических неудач по инструменту в чате.
        cursor = await self._db.db.execute(
            "SELECT episode_id, chat_id, tool_ids_json, created_at "
            "FROM mca_experience_episodes WHERE outcome_kind = 'failure' "
            "AND outcome_source = 'technical' "
            "AND outcome_reliability = 'verified' "
            "ORDER BY created_at DESC, episode_id LIMIT ?", (limit * 4,))
        by_tool: dict[tuple, list[str]] = {}
        for row in await cursor.fetchall():
            row = dict(row)
            chat_id = row.get("chat_id")
            if chat_id is None:
                continue
            for tool in _parse_json_list(row.get("tool_ids_json")):
                tool = str(tool)
                if tool:
                    by_tool.setdefault((int(chat_id), tool), []).append(
                        str(row["episode_id"]))
        for (chat_id, tool), episode_ids in sorted(by_tool.items()):
            unique = list(dict.fromkeys(episode_ids))
            if len(unique) < need:
                continue
            if await self._lesson_exists(type=PROPOSAL_RULE_TOOL_FAILURES[0],
                                         scope="chat", scope_chat_id=chat_id,
                                         rule_key=PROPOSAL_RULE_TOOL_FAILURES[1]):
                skipped += 1
                continue
            created = await self._service.lesson.propose(
                type=PROPOSAL_RULE_TOOL_FAILURES[0], scope="chat",
                rule_key=PROPOSAL_RULE_TOOL_FAILURES[1],
                applicability=f"tool:{tool}", scope_chat_id=chat_id,
                episode_ids=tuple(unique))
            if created is None:
                continue
            candidates.append({
                "lesson_id": created[0], "version": created[1],
                "kind": "generalization",
                "episode_ids": tuple(unique[:need * 4]),
            })

        # P2: ≥need независимых явных коррекций в чате → failure_pattern.
        cursor = await self._db.db.execute(
            "SELECT episode_id, chat_id, created_at "
            "FROM mca_experience_episodes WHERE outcome_kind = 'failure' "
            "AND outcome_source = 'explicit' AND task_type = 'feedback' "
            "ORDER BY created_at DESC, episode_id LIMIT ?", (limit * 4,))
        by_chat: dict[int, list[str]] = {}
        for row in await cursor.fetchall():
            row = dict(row)
            chat_id = row.get("chat_id")
            if chat_id is None:
                continue
            by_chat.setdefault(int(chat_id), []).append(str(row["episode_id"]))
        for chat_id, episode_ids in sorted(by_chat.items()):
            unique = list(dict.fromkeys(episode_ids))
            if len(unique) < need:
                continue
            if await self._lesson_exists(type=PROPOSAL_RULE_CORRECTIONS[0],
                                         scope="chat", scope_chat_id=chat_id,
                                         rule_key=PROPOSAL_RULE_CORRECTIONS[1]):
                skipped += 1
                continue
            created = await self._service.lesson.propose(
                type=PROPOSAL_RULE_CORRECTIONS[0], scope="chat",
                rule_key=PROPOSAL_RULE_CORRECTIONS[1],
                scope_chat_id=chat_id, episode_ids=tuple(unique))
            if created is None:
                continue
            candidates.append({
                "lesson_id": created[0], "version": created[1],
                "kind": "generalization",
                "episode_ids": tuple(unique[:need * 4]),
            })

        # P3: типизированное явное предпочтение участника (self-report):
        # signal_json {"preference": <token>, "user_id": <int>[, "author_user_id"]}.
        cursor = await self._db.db.execute(
            "SELECT feedback_id, chat_id, source_kind, signal_json "
            "FROM mca_experience_feedback WHERE status = 'active' "
            "AND source_kind IN ('owner_correction','participant_correction') "
            "AND signal_json IS NOT NULL "
            "ORDER BY rowid DESC LIMIT ?", (limit,))
        for row in await cursor.fetchall():
            row = dict(row)
            signal = _parse_json_dict(row.get("signal_json"))
            if not signal.get("preference"):
                continue
            try:
                user_id = int(signal.get("user_id"))
                author_id = int(signal.get("author_user_id", user_id))
            except (TypeError, ValueError):
                continue
            if not me.authorize_preference(subject_user_id=user_id,
                                           author_user_id=author_id):
                continue                       # fail-closed (mca-08-модель)
            chat_id = row.get("chat_id")
            if chat_id is None:
                continue
            if await self._lesson_exists(type=PROPOSAL_RULE_PREFERENCE[0],
                                         scope="user_in_chat",
                                         scope_chat_id=int(chat_id),
                                         rule_key=PROPOSAL_RULE_PREFERENCE[1],
                                         scope_user_id=user_id):
                skipped += 1
                continue
            created = await self._service.lesson.propose(
                type=PROPOSAL_RULE_PREFERENCE[0], scope="user_in_chat",
                rule_key=PROPOSAL_RULE_PREFERENCE[1],
                scope_chat_id=int(chat_id), scope_user_id=user_id,
                applicability=f"user:{user_id}")
            if created is None:
                continue
            candidates.append({
                "lesson_id": created[0], "version": created[1],
                "kind": "explicit_preference",
                "episode_ids": (),
            })

        return {"candidates": candidates, "proposed": len(candidates),
                "skipped": skipped}

    async def _lesson_exists(self, *, type: str, scope: str, rule_key: str,
                             scope_chat_id=None, scope_user_id=None) -> bool:
        """Открытый (не superseded) урок с тем же каноном/scope существует?"""
        canonical = me.CANONICAL_RECOMMENDATIONS.get((type, rule_key))
        if canonical is None:
            return True
        try:
            cursor = await self._db.db.execute(
                "SELECT COUNT(*) AS c FROM mca_lessons WHERE status != "
                "'superseded' AND type = ? AND scope = ? AND recommendation = ? "
                "AND (scope_chat_id IS ? OR scope_chat_id = ?) "
                "AND (scope_user_id IS ? OR scope_user_id = ?)",
                (str(type), str(scope), canonical, scope_chat_id,
                 scope_chat_id, scope_user_id, scope_user_id))
            row = await cursor.fetchone()
            return bool(row is not None and int(row["c"]) > 0)
        except Exception:
            return True                        # fail-closed: не плодим дубли

    # ── шаг 3: validate + activate (детерминированные основания) ─────────

    async def _validate_and_activate(self, candidates) -> dict:
        validated = 0
        activated = 0
        for candidate in tuple(candidates or ()):
            lesson_id = str(candidate.get("lesson_id") or "")
            version = int(candidate.get("version") or 0)
            if not lesson_id or version <= 0:
                continue
            kind = str(candidate.get("kind") or "generalization")
            if kind == "explicit_preference":
                lesson = await self._service.get_lesson(lesson_id, version)
                conflict_free = not await self._has_verified_contradiction(
                    lesson) if lesson is not None else False
                evidence = me.ValidationEvidence(
                    kind="explicit_preference", permission_granted=True,
                    conflict_free=conflict_free)
            else:
                independent = tuple(dict.fromkeys(
                    str(x) for x in candidate.get("episode_ids") or () if x))
                if len(independent) < me.ExperiencePolicy \
                        .min_independent_episodes():
                    continue
                evidence = me.ValidationEvidence(
                    kind="generalization",
                    independent_episode_ids=independent)
            if await self._service.lesson.validate(
                    lesson_id, version, evidence=evidence):
                validated += 1
                if await self._service.lesson.activate(lesson_id, version):
                    activated += 1
        return {"validated": validated, "activated": activated}

    async def _has_verified_contradiction(self, lesson: dict) -> bool:
        """Проверенное противоречие уроку (mca-04a evidence links; read-only)."""
        ref_id = lesson.get("source_ref_id")
        if ref_id is None:
            return False
        try:
            cursor = await self._db.db.execute(
                "SELECT COUNT(*) AS c FROM mca_evidence_links WHERE "
                "subject_ref_id = ? AND link_type = 'contradicts' AND "
                "verification = 'verified'", (int(ref_id),))
            row = await cursor.fetchone()
            return bool(row is not None and int(row["c"]) > 0)
        except Exception:
            return True                        # fail-closed: не активируем

    # ── шаг 4: suspend (сильное противоречие — не спор) ──────────────────

    async def _suspend_contradicted(self) -> int:
        cursor = await self._db.db.execute(
            "SELECT l.lesson_id, l.version FROM mca_lessons l "
            "WHERE l.status = 'active' AND l.source_ref_id IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM mca_evidence_links e WHERE "
            "e.subject_ref_id = l.source_ref_id AND e.link_type = "
            "'contradicts' AND e.verification = 'verified')")
        count = 0
        for row in await cursor.fetchall():
            if await self._service.lesson.suspend(
                    str(row["lesson_id"]),
                    reason_code="contradictory_evidence"):
                count += 1
        return count

    # ── шаг 5: outcome-link + шаг 6: utility-update ──────────────────────

    async def _link_outcomes(self) -> int:
        """Исход → реально применённый урок (идемпотентно, позже применения).

        Только независимые типизированные события (technical/explicit) с
        `reliability=verified` и `created_at >= applied_at`; unknown/social/
        LLM не улучшают success/failure. «Применение ≠ причинность»."""
        limit = me.ExperiencePolicy.review_batch_max()
        cursor = await self._db.db.execute(
            "SELECT application_id, lesson_id, lesson_version, "
            "application_ref, trace_id, chat_id, applied_at "
            "FROM mca_lesson_applications WHERE outcome = 'unknown' "
            "AND linked_at IS NULL ORDER BY application_id LIMIT ?", (limit,))
        linked = 0
        for row in await cursor.fetchall():
            row = dict(row)
            chat_id, trace_id = row.get("chat_id"), row.get("trace_id")
            if chat_id is None or not trace_id:
                continue
            try:
                episodes = await self._service.store.find_episodes_by_ref(
                    chat_id, trace_id=str(trace_id), limit=5)
            except Exception:
                episodes = []
            for episode in episodes:
                if str(episode.get("outcome_kind")) not in ("success",
                                                            "failure"):
                    continue
                if str(episode.get("outcome_reliability")) != "verified":
                    continue
                if _episode_event_ts(episode) < int(
                        row.get("applied_at") or 0):
                    continue                       # исход должен быть позже
                lesson = await self._service.get_lesson(
                    str(row["lesson_id"]), int(row["lesson_version"]))
                measurement = _MEASUREMENT_BY_TYPE.get(
                    str((lesson or {}).get("type") or ""))
                ok = await self._service.link_application_outcome(
                    lesson_id=str(row["lesson_id"]),
                    version=int(row["lesson_version"]),
                    application_ref=str(row["application_ref"] or trace_id),
                    outcome=str(episode.get("outcome_kind")),
                    outcome_source=str(episode.get("outcome_source")),
                    measurement=measurement,
                    outcome_ref=str(episode.get("episode_id")))
                if ok:
                    linked += 1
                break
        return linked

    # ── шаг 7: recheck (совместимость; без выдуманного успеха) ───────────

    async def _recheck_stale(self) -> int:
        """Смена tool schema/model/config → recheck_required=1 (не применяется).

        Повторная проверка выполняется только по реальному контрольному
        примеру (существующие пути/fixtures); job не выдумывает успех."""
        return await self._service.lesson.recheck_stale()

    # ── шаг 8: prune (retention; связанное с уроками/lineage не трогаем) ─

    async def _prune(self) -> dict:
        """Retention через `ExperiencePolicy.*` (bounded; GEN-R8).

        Никогда не прунятся строки, на которые ссылаются уроки/lineage
        (episode source refs) или feedback; применения active/validated
        уроков сохраняются."""
        now = int(time.time())
        episode_cutoff = now - \
            me.ExperiencePolicy.episode_retention_days() * 86400
        feedback_cutoff = now - \
            me.ExperiencePolicy.feedback_retention_days() * 86400
        application_cutoff = now - \
            me.ExperiencePolicy.application_retention_days() * 86400

        async def _body(conn):
            cursor = await conn.execute(
                "DELETE FROM mca_experience_episodes WHERE episode_id IN ("
                "SELECT episode_id FROM mca_experience_episodes "
                "WHERE created_at < ? AND episode_id NOT IN ("
                "SELECT entity_id FROM mca_source_refs WHERE entity_type = "
                "'episode') AND episode_id NOT IN ("
                "SELECT episode_id FROM mca_experience_feedback WHERE "
                "episode_id IS NOT NULL) LIMIT ?)",
                (episode_cutoff, _PRUNE_BATCH))
            pruned_episodes = int(cursor.rowcount or 0)
            cursor = await conn.execute(
                "DELETE FROM mca_experience_feedback WHERE feedback_id IN ("
                "SELECT feedback_id FROM mca_experience_feedback WHERE ts < ? "
                "LIMIT ?)", (feedback_cutoff, _PRUNE_BATCH))
            pruned_feedback = int(cursor.rowcount or 0)
            cursor = await conn.execute(
                "DELETE FROM mca_lesson_applications WHERE application_id IN ("
                "SELECT a.application_id FROM mca_lesson_applications a "
                "WHERE a.applied_at < ? AND NOT EXISTS ("
                "SELECT 1 FROM mca_lessons l WHERE l.lesson_id = a.lesson_id "
                "AND l.version = a.lesson_version AND l.status IN "
                "('active','validated')) LIMIT ?)",
                (application_cutoff, _PRUNE_BATCH))
            pruned_applications = int(cursor.rowcount or 0)
            return {"pruned_episodes": pruned_episodes,
                    "pruned_feedback": pruned_feedback,
                    "pruned_applications": pruned_applications}

        try:
            return await self._db.write_transaction(
                _body, op_name="mca16_review_prune")
        except Exception:
            logger.warning("[mca16] review prune failed — skip",
                           exc_info=True)
            return {"pruned_episodes": 0, "pruned_feedback": 0,
                    "pruned_applications": 0}


# ── T-5010: temporal holdout (честный отчёт, не доказательство) ─────────────

async def temporal_holdout_report(db, *, chat_id: int, query: str,
                                  lessons_before: bool = True) -> dict:
    """T-5010/§25.7: temporal holdout — уроки только из прошлого.

    Методика (детерминированная, без LLM): review-job извлекает уроки из
    эпизодов фазы 1 (прошлое); фаза 2 (позже) — проверочные эпизоды, которые
    НЕ были источником (evidence links проверяются явно). OFF/ON-сравнение —
    на одной версии модели/сопоставимом запросе: OFF (K4) → уроки не
    отбираются (bundle = 2.58.58); ON → отбор + bounded-блок.

    Честность (A57/GEN-R27): `improvement_measured=False` — replay без
    реального человеческого outcome проверяет инварианты, но не доказывает
    реакцию человека; отсутствие измеренного улучшения не подменяется числом
    созданных уроков."""
    service = me.get_service(db)
    if lessons_before:
        # Review на фазе 1 (только прошлое): job-путь (capture+propose+
        # validate+activate) — те же шаги, что в расписании.
        try:
            job_id = await enqueue_experience_review(db)
            if job_id:
                await ExperienceReviewRunner(db).run(job_id)
        except Exception:
            logger.warning("[mca16] holdout review run failed", exc_info=True)
    lessons = await service.list_lessons(chat_id=int(chat_id), limit=200)
    active = [x for x in lessons if str(x.get("status")) == "active"]
    source_ids: set[str] = set()
    for lesson in active:
        ref_id = lesson.get("source_ref_id")
        if ref_id is None:
            continue
        try:
            cursor = await db.db.execute(
                "SELECT r.entity_id AS episode_id FROM mca_evidence_links l "
                "JOIN mca_source_refs r ON r.source_ref_id = l.source_ref_id "
                "WHERE l.subject_ref_id = ? AND r.entity_type = 'episode'",
                (int(ref_id),))
            for row in await cursor.fetchall():
                source_ids.add(str(row["episode_id"]))
        except Exception:
            continue
    cursor = await db.db.execute(
        "SELECT episode_id, created_at, decision_json, outcome_kind FROM "
        "mca_experience_episodes WHERE chat_id = ? "
        "ORDER BY created_at, episode_id LIMIT 1000", (int(chat_id),))
    episodes = [dict(r) for r in await cursor.fetchall()]
    source_ts = [_episode_event_ts(e) for e in episodes
                 if str(e["episode_id"]) in source_ids]
    validation = [e for e in episodes
                  if str(e["episode_id"]) not in source_ids
                  and (not source_ts
                       or _episode_event_ts(e) > max(source_ts))]
    validation_failures = sum(
        1 for e in validation if str(e.get("outcome_kind")) == "failure")
    # OFF/ON на одной модели: OFF — K4-ветка отбора (disabled), ON — реальный
    # отбор с query. Никаких изменений гейтов — только вызовы сервиса.
    off_result = me.SelectionResult(reason_code="disabled")
    on_result = await service.lesson.select_for_context(
        chat_id=int(chat_id), query=str(query or ""))
    block = me.render_lessons_block(on_result.lessons)
    block_tokens = (len(block) + 3) // 4 if block else 0
    return {
        "chat_id": int(chat_id),
        "query": str(query or ""),
        "lessons_total": len(lessons),
        "lessons_active": len(active),
        "source_episode_ids": sorted(source_ids),
        "validation_episodes": len(validation),
        "validation_failures": validation_failures,
        "sources_after_validation": bool(
            source_ts and validation
            and max(source_ts) > max(_episode_event_ts(e) for e in validation)),
        "off_selected": len(off_result.lessons),
        "on_selected": len(on_result.lessons),
        "block_tokens": block_tokens,
        "block_max_tokens": me.ExperiencePolicy.block_max_tokens(),
        # Честно: replay не измеряет реакцию человека и не доказывает
        # улучшение; correctness/appropriateness требуют живого сигнала.
        "improvement_measured": False,
        "correctness": None,
        "appropriateness": None,
        "extra_cost_tokens": block_tokens,
        "note": ("replay без реального outcome проверяет инварианты "
                 "(уроки из прошлого; проверочные эпизоды не были источником; "
                 "bounded-блок), но не доказывает реакцию человека; "
                 "измеренного улучшения нет — число созданных уроков не "
                 "подменяет эффект"),
    }
