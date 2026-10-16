"""ASAP 4.1 волна 5 (эпик `asap-4-1-durable-whole-window-summary`) —
Durable SummaryRun: persistent state machine + append-only stage events
(T-4616, spec §5 E.1; ADR-1028-8 D6; SQLite v24 `summary_runs` +
`summary_run_stages`, additive; PostgreSQL — no-op).

Решение (носитель): dedicated additive SQLite-таблицы — НЕ task_jobs
payload (L-EXTRA-6 не наследуется: checkpoint run-state живёт в
`summary_runs`, а не в перезаписываемой payload-колонке) и НЕ перегрузка
`mca_pipeline_runs` (тот остаётся root-lifecycle/heartbeat mca-17a).
task_jobs (v14) остаются execution-носителем (heartbeat/fencing/resume
очереди — TaskJobStore REUSE); стабильный `summary_run_id` создаётся
один раз и персистится здесь (L-EXTRA-7 закрыт; cover-джоба уже
ключуется от run_id — cover-style jobs ``cover_job_key``).

State machine §20 (22936–22951):
  CREATED → SOURCE_READY → STRUCTURING → STRUCTURE_READY → WRITING
  → REVIEWING → TEXT_READY → BASE_COVER → STYLE_EDIT → PUBLISHING → DONE
  (любая стадия → DEGRADED | FAILED)

`summary_run_stages` — append-only §50.54: каждая стадия/попытка = новая
строка (begin → terminal-UPDATE статуса строки; DELETE истории не
существует; retry = НОВАЯ строка).

Kill-switch `SUMMARY_RUN_DURABLE_ENABLED` (env-only, default ON; OFF →
runs не персистятся, workflow как сегодня — бит-в-бит 2.58.46;
stage_events append-only семантика in-memory RunContext остаётся
независимо). Резолв per-call, никогда не бросает (прецедент
`summary_l1_capacity.capacity_guard_enabled`).

Интеграция с `summary_run_log.py` RunContext — не дубль (R6-C-001):
RunContext — in-memory витрина прогона; этот store — durable checkpoint.
"""
from __future__ import annotations

import logging
import os
import time

from config.settings import settings

logger = logging.getLogger(__name__)

SCHEMA_RUNS = "summary_runs"
SCHEMA_STAGES = "summary_run_stages"

# ── State machine §20 (ТЗ 22936–22951) ──────────────────────────────────────

STATE_CREATED = "CREATED"
STATE_SOURCE_READY = "SOURCE_READY"
STATE_STRUCTURING = "STRUCTURING"
STATE_STRUCTURE_READY = "STRUCTURE_READY"
STATE_WRITING = "WRITING"
STATE_REVIEWING = "REVIEWING"
STATE_TEXT_READY = "TEXT_READY"
STATE_BASE_COVER = "BASE_COVER"
STATE_STYLE_EDIT = "STYLE_EDIT"
STATE_PUBLISHING = "PUBLISHING"
STATE_DONE = "DONE"
STATE_DEGRADED = "DEGRADED"
STATE_FAILED = "FAILED"

TERMINAL_STATES = (STATE_DONE, STATE_DEGRADED, STATE_FAILED)

# Порядок стадий для rank-guard'а: checkpoint не отматывается назад
# (resume §21 — продолжение, а не пересоздание; повторный STRUCTURING
# на докатываемом run'е не сбрасывает WRITING/TEXT_READY назад).
_STATE_RANK: dict[str, int] = {
    STATE_CREATED: 0, STATE_SOURCE_READY: 1, STATE_STRUCTURING: 2,
    STATE_STRUCTURE_READY: 3, STATE_WRITING: 4, STATE_REVIEWING: 5,
    STATE_TEXT_READY: 6, STATE_BASE_COVER: 7, STATE_STYLE_EDIT: 8,
    STATE_PUBLISHING: 9, STATE_DONE: 10, STATE_DEGRADED: 11,
    STATE_FAILED: 12,
}


def state_rank(state: str) -> int:
    """Порядковый номер стадии state machine (неизвестное → -1)."""
    return _STATE_RANK.get(str(state or ""), -1)

# Допустимые переходы (проверяются тестом; runtime — fail-open: невозможный
# переход логируется, но не рвёт пайплайн).
VALID_TRANSITIONS: dict[str, tuple[str, ...]] = {
    STATE_CREATED: (STATE_SOURCE_READY, STATE_DEGRADED, STATE_FAILED),
    STATE_SOURCE_READY: (STATE_STRUCTURING, STATE_DEGRADED, STATE_FAILED),
    STATE_STRUCTURING: (STATE_STRUCTURE_READY, STATE_DEGRADED,
                        STATE_FAILED),
    STATE_STRUCTURE_READY: (STATE_WRITING, STATE_DEGRADED, STATE_FAILED),
    STATE_WRITING: (STATE_REVIEWING, STATE_TEXT_READY, STATE_DEGRADED,
                    STATE_FAILED),
    STATE_REVIEWING: (STATE_TEXT_READY, STATE_DEGRADED, STATE_FAILED),
    STATE_TEXT_READY: (STATE_BASE_COVER, STATE_PUBLISHING, STATE_DEGRADED,
                       STATE_FAILED),
    STATE_BASE_COVER: (STATE_STYLE_EDIT, STATE_PUBLISHING, STATE_DEGRADED,
                       STATE_FAILED),
    STATE_STYLE_EDIT: (STATE_PUBLISHING, STATE_DEGRADED, STATE_FAILED),
    STATE_PUBLISHING: (STATE_DONE, STATE_DEGRADED, STATE_FAILED),
    STATE_DONE: (),
    STATE_DEGRADED: (),
    STATE_FAILED: (),
}


def transition_allowed(from_state: str, to_state: str) -> bool:
    """Валидатор перехода state machine (тест-поверхность; runtime
    fail-open — неизвестные состояния считаются допустимыми)."""
    allowed = VALID_TRANSITIONS.get(str(from_state or ""))
    if allowed is None:
        return True             # неизвестное состояние — не блокируем
    return str(to_state) in allowed


# ── publication_status (T-4617, ADR-1028-8 D6.2) ────────────────────────────

PUBLICATION_PENDING = "pending"
PUBLICATION_PUBLISHING = "publishing"
PUBLICATION_PUBLISHED = "published"
PUBLICATION_FAILED = "failed"


def run_durable_enabled() -> bool:
    """Kill-switch ``SUMMARY_RUN_DURABLE_ENABLED`` (env-only, default ON;
    резолв per-call; никогда не бросает)."""
    try:
        return bool(getattr(settings, "SUMMARY_RUN_DURABLE_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def _row_get(row, name):
    if row is None:
        return None
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return getattr(row, name, None)


# ── Run lifecycle wrappers (SQL — database.py; fail-open, run не рвём) ─────

async def create_run(db, run_id: str, chat_id: int, *, manual: bool = False,
                     state: str = STATE_CREATED) -> bool:
    """Создать run-row (INSERT OR IGNORE — один раз на стабильный run_id)."""
    if not run_durable_enabled() or db is None or not run_id:
        return False
    return await db.create_summary_run(
        run_id=str(run_id), chat_id=int(chat_id), state=state,
        manual=bool(manual))


async def set_state(db, run_id: str, state: str, *, window_from=None,
                    window_to=None, source_ref: str | None = None,
                    pipeline_health: str | None = None) -> bool:
    """Checkpoint run-state (§20). Rank-guard: назад (к младшей стадии)
    checkpoint не отматывается (resume — продолжение; лог-отметка без
    записи). Терминальные состояния не переписываются. Fail-open: OFF/нет
    БД/no-op."""
    if not run_durable_enabled() or db is None or not run_id:
        return False
    try:
        run = await db.get_summary_run(str(run_id))
        if run is not None:
            current = str(run.get("state") or "")
            if current in TERMINAL_STATES \
                    and str(state) not in TERMINAL_STATES:
                return False        # терминальный run не реанимируется
            if state_rank(str(state)) >= 0 \
                    and state_rank(str(state)) < state_rank(current) \
                    and current not in TERMINAL_STATES:
                logger.debug(
                    "[summary41] state rewind skipped | run_id=%s | %s → %s",
                    str(run_id)[:64], current, state)
                return False
    except Exception:      # pragma: no cover - fail-open
        pass
    return await db.update_summary_run_state(
        str(run_id), str(state), window_from=window_from,
        window_to=window_to, source_ref=source_ref,
        pipeline_health=pipeline_health)


async def get_run(db, run_id: str) -> dict | None:
    """Прочитать run-row (restart-safe; OFF/нет → None)."""
    if not run_durable_enabled() or db is None or not run_id:
        return None
    return await db.get_summary_run(str(run_id))


async def record_stage(db, run_id: str, stage: str, *, status: str = "ok",
                       started_at: int | None = None, attempt: int = 0,
                       provider: str | None = None, model: str | None = None,
                       result_ref: str | None = None,
                       reason_code: str | None = None) -> int | None:
    """Append-only stage event (§50.54): одна строка на завершённую
    стадию/попытку; retry = НОВАЯ строка; DELETE/UPDATE истории нет."""
    if not run_durable_enabled() or db is None or not run_id:
        return None
    return await db.record_summary_run_stage(
        str(run_id), str(stage), status=str(status), started_at=started_at,
        attempt=attempt, provider=provider, model=model,
        result_ref=result_ref, reason_code=reason_code)


async def mark_publishing(db, run_id: str) -> tuple[bool, str | None]:
    """Фиксация PUBLISHING ДО отправки (T-4617, ADR-1028-8 D6.2).

    Возвращает ``(proceed, current_status)``:
      * ``(False, "published")`` — публикация уже зафиксирована: НЕ
        публиковать (двойной финальный месседж невозможен);
      * ``(False, "publishing")`` — PUBLISHING уже зафиксирован другим
        заходом (kill-recovery): вызывающий обязан сперва пройти
        content-hash барьер `bot_output_ledger` (reconcile R4-D-051);
      * ``(True, <старый статус>)`` — фиксация записана, отправлять.

    Идемпотентность: существующий `published` в БД никогда не
    перезаписывается (set_summary_run_publication no-op)."""
    if not run_durable_enabled() or db is None or not run_id:
        return True, None
    run = await get_run(db, str(run_id))
    if run is None:
        return True, None
    status = str(run.get("publication_status") or "") or None
    if status == PUBLICATION_PUBLISHED:
        return False, PUBLICATION_PUBLISHED
    if status != PUBLICATION_PUBLISHING:
        await db.set_summary_run_publication(str(run_id),
                                             PUBLICATION_PUBLISHING)
        return True, status
    return False, PUBLICATION_PUBLISHING


async def complete_publication(db, run_id: str, *,
                               result_ref: str | None = None) -> bool:
    """publication_status = published (после успешной send)."""
    if not run_durable_enabled() or db is None or not run_id:
        return False
    return await db.set_summary_run_publication(
        str(run_id), PUBLICATION_PUBLISHED,
        result_ref=str(result_ref) if result_ref else None)


async def fail_publication(db, run_id: str) -> bool:
    """publication_status = failed (ни один канал не доставил)."""
    if not run_durable_enabled() or db is None or not run_id:
        return False
    return await db.set_summary_run_publication(
        str(run_id), PUBLICATION_FAILED)


async def last_completed_stage(db, run_id: str) -> dict | None:
    """Последняя успешно завершённая стадия (resume §21: продолжение с
    неё, не начинать заново)."""
    if not run_durable_enabled() or db is None or not run_id:
        return None
    return await db.last_completed_summary_run_stage(str(run_id))


async def stage_history(db, run_id: str) -> list[dict]:
    """Append-only stage-история run'а (structured state, не логи)."""
    if not run_durable_enabled() or db is None or not run_id:
        return []
    return await db.list_summary_run_stages(str(run_id))


def run_has_window(run) -> bool:
    """Есть ли у run'а durable окно (source_ref/window_from/window_to).

    INC-SUMMARY-01: ран без окна после рестарта докатывать нечего — его
    закрывают терминалом (``close_stale_run``), а не «резюмят» вслепую."""
    if not run:
        return False
    return any(_row_get(run, name) is not None
               for name in ("source_ref", "window_from", "window_to"))


def run_age_seconds(run, *, now: int | None = None) -> int | None:
    """Возраст run'а от ``created_at`` (None — метки нет/нечитаема)."""
    try:
        created = int(_row_get(run, "created_at"))
    except (TypeError, ValueError):
        return None
    return max(0, int(now if now is not None else time.time()) - created)


async def close_stale_run(db, run_id: str, *,
                          reason_code: str = "stale_no_window") -> bool:
    """Терминал УСТАРЕВШЕГО нетерминального run'а (INC-SUMMARY-01).

    FAILED + стадия ``run`` с ``reason_code`` — и БЕЗ касания
    ``publication_status``: у такого рана нет окна, значит публикации не было
    и не будет (повторная отправка невозможна, второй живой run_id под ту же
    запись не создаётся — следующий прогон получает свой run_id).

    INC-FIX-RESIDUAL (17.10.2026): закрывая ран, финализатор обязан оставить
    и ТЕРМИНАЛЬНОЕ СОБЫТИЕ (`SUMMARY_RUN_DONE`) — иначе durable-состояние
    FAILED и дериват UI расходятся: Oversight/Status выводит «running» из
    `mca_events` (START без терминала), т.е. у закрытого рана бейдж читался
    «running» (прод-факт 2.58.82, ран `da33f05d…`)."""
    ok = await set_state(db, run_id, STATE_FAILED)
    if not ok:
        return False
    await record_stage(db, run_id, "run", status="failed",
                       reason_code=reason_code)
    await _emit_closed_run_terminal_event(db, run_id, reason_code)
    return True


async def _emit_closed_run_terminal_event(db, run_id: str,
                                          reason_code: str) -> None:
    """`SUMMARY_RUN_DONE` для рана, закрытого финализатором (fail-open).

    Та же точка контракта, что у штатного `finally` прогона
    (`pipeline_events.summary_done_from_ctx`) — обе поверхности (durable-строка
    и дериват из `mca_events`) читают один и тот же терминал. `chat_id` берём
    из самой run-строки (строка в UI не должна оставаться без чата). Сбой
    эмиссии терминал в `summary_runs` НЕ отменяет и остановку не рвёт."""
    chat_id = None
    try:
        run = await get_run(db, str(run_id))
        chat_id = _row_get(run, "chat_id")
    except Exception:            # pragma: no cover - fail-open
        chat_id = None
    try:
        from services import pipeline_events
        pipeline_events.summary_done(
            run_id, chat_id=chat_id, status="failed", health="failed",
            reason_code=reason_code)
    except Exception:            # pragma: no cover - эмиссия не рвёт закрытие
        logger.warning("[summary41] closed-run terminal event failed — "
                       "fail-open | run_id=%s", str(run_id)[:64], exc_info=True)


# ── Startup-recovery нетерминальных ранов (INC-SUMMARY-01, 17.10.2026) ─────
# Прод-инцидент: процесс убит SIGKILL'ом (рестарт деплоя) → `finally` не
# исполнился → run-row навсегда осталась нетерминальной, а UI/Oversight
# выводил из неё «running». Watchdog репает только `task_jobs`; summary-run
# не финализировал никто. Финализатор на старте процесса закрывает такие
# раны тем же терминалом, что и stale-closer (без дубля логики).

_ORPHAN_GRACE_ENV = "SUMMARY_ORPHAN_GRACE_SECONDS"
_ORPHAN_GRACE_DEFAULT = 30.0


def orphan_grace_seconds() -> float:
    """Окно защиты СВЕЖЕГО рана при startup-recovery (env-only, per-call).

    Страхует пред-генерационный ран ДРУГОГО живого процесса (оверлап
    деплоя/ручной запуск): ран младше окна не закрывается — его закроет
    штатный stale-closer следующего прогона этого чата."""
    raw = os.getenv(_ORPHAN_GRACE_ENV, "").strip()
    if not raw:
        return _ORPHAN_GRACE_DEFAULT
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        logger.warning("[summary41] %s=%r не число — берём default %s",
                       _ORPHAN_GRACE_ENV, raw, _ORPHAN_GRACE_DEFAULT)
        return _ORPHAN_GRACE_DEFAULT


async def list_nonterminal_runs(db) -> list[dict]:
    """Read-only выборка нетерминальных run'ов (startup-recovery).

    Читает тот же SQLite-коннект, что и остальные durable-вызовы (SELECT —
    без single-writer). Fail-open → ``[]`` (OFF kill-switch / нет БД / сбой)."""
    if not run_durable_enabled() or db is None:
        return []
    try:
        conn = getattr(db, "db", None)
        if conn is None:
            return []
        placeholders = ",".join("?" * len(TERMINAL_STATES))
        cursor = await conn.execute(
            "SELECT run_id, chat_id, state, created_at, source_ref, "
            "window_from, window_to FROM summary_runs "
            f"WHERE state NOT IN ({placeholders})",
            tuple(TERMINAL_STATES))
        return [dict(row) for row in await cursor.fetchall()]
    except Exception:          # pragma: no cover - fail-open
        logger.warning("[summary41] nonterminal run scan failed — fail-open",
                       exc_info=True)
        return []


async def close_orphan_runs(db, *, reason_code: str = "orphan_no_owner",
                            grace_seconds: float | None = None,
                            live_run_ids=None,
                            now: int | None = None) -> list[dict]:
    """Startup-recovery: терминал для нетерминальных ранов БЕЗ живого владельца.

    Вызывается на старте процесса (владельцев нет по определению). Семантика
    = stale-closer (``close_stale_run``): FAILED + стадия ``run``/``reason_code``
    и БЕЗ касания ``publication_status`` (окна нет → публикации не было и не
    будет; повторной отправки не возникает, второй живой run_id под ту же
    запись не создаётся). Ран С durable окном НЕ закрывается — докатывается
    по контракту resume (§21). Ран младше ``grace_seconds`` не закрывается
    (возможный оверлап живого процесса). Возвращает список закрытых."""
    result: list[dict] = []
    grace = orphan_grace_seconds() if grace_seconds is None \
        else max(0.0, float(grace_seconds))
    for run in await list_nonterminal_runs(db):
        run_id = str(_row_get(run, "run_id") or "")
        if not run_id:
            continue
        if live_run_ids and run_id in live_run_ids:
            continue
        chat_id = _row_get(run, "chat_id")
        age = run_age_seconds(run, now=now)
        if run_has_window(run):
            logger.info(
                "SUMMARY_ORPHAN_RUN_KEPT | run_id=%s | chat_id=%s | age_s=%s | "
                "reason=has_window — докатывается по контракту resume (§21)",
                run_id, chat_id, age)
            continue
        if age is not None and grace and age < grace:
            logger.info(
                "SUMMARY_ORPHAN_RUN_KEPT | run_id=%s | chat_id=%s | age_s=%s | "
                "reason=within_grace — окно защиты живого процесса (grace_s=%s)",
                run_id, chat_id, age, grace)
            continue
        closed = await close_stale_run(db, run_id, reason_code=reason_code)
        logger.warning(
            "SUMMARY_ORPHAN_RUN_CLOSED | run_id=%s | chat_id=%s | state=%s | "
            "age_s=%s | closed=%s | reason=%s — нетерминальный ран без живого "
            "владельца закрыт FAILED (публикация не трогалась)",
            run_id, chat_id, _row_get(run, "state"), age, closed, reason_code)
        result.append({"run_id": run_id, "chat_id": chat_id, "age_s": age,
                       "closed": bool(closed)})
    return result


def terminal_state_for_run(*, status: str | None, health: str | None,
                           published: bool | None = None) -> str:
    """Терминальное состояние прогона по RunContext (§20/§61.13):
    FAILED — прогона не было/упал; DONE — публикация ok и health ok;
    DEGRADED — опубликовано с деградацией (fallback/coverage/review)."""
    if (status or "") == "failed":
        return STATE_FAILED
    if published is False:
        return STATE_FAILED
    if (health or "ok") == "ok":
        return STATE_DONE
    return STATE_DEGRADED


async def purge_expired_runs(db, *, now: int | None = None) -> int:
    """TTL-очистка терминальных run'ов + их стадий/окон (T-4616: гейт —
    ТОЛЬКО после DONE/DEGRADED/FAILED; незавершённые не задеваются)."""
    if not run_durable_enabled() or db is None:
        return 0
    try:
        from services.summary_source_window import retention_days
        horizon = retention_days() * 86400
    except Exception:      # pragma: no cover - защитная ветка
        horizon = 7 * 86400
    cutoff = int(now if now is not None else time.time()) - horizon
    return await db.purge_expired_summary_runs(
        before_ts=cutoff, terminal_states=TERMINAL_STATES)


__all__ = [
    "SCHEMA_RUNS", "SCHEMA_STAGES",
    "STATE_CREATED", "STATE_SOURCE_READY", "STATE_STRUCTURING",
    "STATE_STRUCTURE_READY", "STATE_WRITING", "STATE_REVIEWING",
    "STATE_TEXT_READY", "STATE_BASE_COVER", "STATE_STYLE_EDIT",
    "STATE_PUBLISHING", "STATE_DONE", "STATE_DEGRADED", "STATE_FAILED",
    "TERMINAL_STATES", "VALID_TRANSITIONS", "transition_allowed",
    "state_rank",
    "PUBLICATION_PENDING", "PUBLICATION_PUBLISHING",
    "PUBLICATION_PUBLISHED", "PUBLICATION_FAILED",
    "run_durable_enabled", "create_run", "set_state", "get_run",
    "record_stage", "mark_publishing",
    "complete_publication", "fail_publication", "last_completed_stage",
    "stage_history", "terminal_state_for_run", "purge_expired_runs",
    "run_has_window", "run_age_seconds", "close_stale_run",
    "list_nonterminal_runs", "close_orphan_runs", "orphan_grace_seconds",
]
