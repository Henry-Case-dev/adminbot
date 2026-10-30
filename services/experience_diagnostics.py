"""EVOL-020 — жива ли цепочка «опыт → урок → проверка → применение → исход».

Проблема, которую решает модуль (plans/current_task.md, EVOL-020): экран
показывает «работает» и одновременно застоявшиеся числа («Замечено 7»,
«Уроков 0» на верхнем графике при «Уроков 2» в детализации, «Проверено 2»,
«Применено 0», «Помогло 0»). Числа могут описывать разные классы и периоды —
но без источника и окна их нельзя ни объяснить, ни опровергнуть.

Модуль ТОЛЬКО ЧИТАЕТ существующие durable-источники и возвращает для каждого
этапа цепочки:

* `last_run_at` / `last_success_at` (реальные отметки, `None` = «не было»);
* счётчики за 24ч / 7д / 30д И `total`, чтобы разница total ↔ окно была
  объяснена, а не выдумана;
* причины пропусков (типизированные события `mca_events`), а не догадки;
* состояние этапа и всей цепочки: `working` / `idle` / `broken` / `disabled`
  / `stale` / `never_run`.

Инварианты:
* никаких новых уроков, применений или «подогретых» счётчиков — только
  фактические строки существующих таблиц (`mca_experience_episodes`,
  `mca_experience_feedback`, `mca_lessons`, `mca_lesson_applications`,
  `task_jobs`, `mca_events`);
* «ноль применений» НЕ равен «сломалось»: причина (`no_active_lessons`,
  `nothing_matched`, `context_off`) выводится из данных отдельно;
* «scheduler существует» НЕ равен «работает»: состояние берётся из реальных
  прогонов и их исходов;
* R17: наружу — id/коды/числа/enum, без текста уроков и приватных данных.

DX/UI-слой (роут/карточка) — отдельная полоса: здесь только сервисные функции
и данные.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

#: Этапы цепочки в порядке следования (лейблы — для витрины, не для логики).
PIPELINE_STAGES = (
    "observation", "candidate", "validation", "activation",
    "retrieval", "application", "outcome", "utility",
)

STAGE_LABELS = {
    "observation": "Наблюдение (эпизоды опыта и feedback)",
    "candidate": "Кандидат в урок",
    "validation": "Проверка урока",
    "activation": "Активация урока",
    "retrieval": "Отбор урока в контекст",
    "application": "Применение урока",
    "outcome": "Измеренный исход",
    "utility": "Полезность (счётчики)",
}

#: Состояния (закрытый набор; словарь определений уходит в ответ).
STATE_WORKING = "working"
STATE_IDLE = "idle"
STATE_BROKEN = "broken"
STATE_DISABLED = "disabled"
STATE_STALE = "stale"
STATE_NEVER_RUN = "never_run"

STATE_LABELS = {
    STATE_WORKING: "Работает: есть свежие результаты цепочки",
    STATE_IDLE: "Простаивает: запускается, но достойных уроков пока нет",
    STATE_BROKEN: "Ошибка: последний прогон завершился неудачей",
    STATE_DISABLED: "Выключено настройкой",
    STATE_STALE: "Давно не запускалось (планировщик не доходит)",
    STATE_NEVER_RUN: "Ещё не запускалось",
}

#: Окна счётчиков (24ч/7д/30д — требование EVOL-020; фиксированные константы).
WINDOW_24H = 24 * 3600
WINDOW_7D = 7 * 86400
WINDOW_30D = 30 * 86400

#: Типизированные события контура опыта (существующий словарь mca-13; второй
#: не вводится). Используются как причины/отметки этапов, не как агрегаты.
EXPERIENCE_EVENT_NAMES = (
    "experience_recorded", "lesson_proposed", "validation_passed",
    "validation_failed", "activated", "retrieved", "applied",
    "feedback_linked", "utility_updated", "suspended", "superseded",
)

#: Причины, объясняющие «ноль применений» — по данным, без догадок.
REASON_NO_ACTIVE_LESSONS = "no_active_lessons"
REASON_NOTHING_MATCHED = "nothing_matched"
REASON_CONTEXT_OFF = "context_selection_off"
REASON_NO_SELECTION_RUN = "no_selection_runs"
REASON_NO_APPLICATIONS = "no_applications_recorded"
REASON_NO_WORTHY_LESSONS = "no_worthy_lessons"
REASON_NO_NEW_OBSERVATIONS = "no_new_observations"
REASON_LAST_RUN_FAILED = "last_run_failed"
REASON_NO_RECENT_RUNS = "no_recent_runs"
REASON_NO_REVIEW_RUNS = "no_review_runs"
REASON_DISABLED = "learning_disabled"
REASON_RUN_IN_PROGRESS = "run_in_progress"
REASON_LESSONS_FLOWING = "lessons_flowing"
REASON_APPLICATIONS_FLOWING = "applications_flowing"
REASON_OUTCOMES_MEASURED = "outcomes_measured"

REASON_LABELS = {
    REASON_NO_ACTIVE_LESSONS: (
        "Нет активных уроков — применять нечего (это не ошибка)"),
    REASON_NOTHING_MATCHED: (
        "Активные уроки есть, но ни один не прошёл отбор по релевантности"),
    REASON_CONTEXT_OFF: (
        "Отбор уроков в контекст выключен настройкой (K4)"),
    REASON_NO_SELECTION_RUN: (
        "Отбор уроков ещё ни разу не запускался в этом scope"),
    REASON_NO_APPLICATIONS: (
        "Применения не записывались: не было генерации с блоком уроков"),
    REASON_NO_WORTHY_LESSONS: (
        "Наблюдения есть, но достойных уроков пока не появилось"),
    REASON_NO_NEW_OBSERVATIONS: (
        "Новых наблюдений в окне нет — цепочка ждёт подходящего случая"),
    REASON_LAST_RUN_FAILED: "Последний прогон review завершился ошибкой",
    REASON_NO_RECENT_RUNS: (
        "Прогонов не было дольше двух каденций — планировщик не доходит"),
    REASON_NO_REVIEW_RUNS: "Прогонов review ещё не было",
    REASON_DISABLED: "Обучение выключено настройкой — новые уроки не пишутся",
    REASON_RUN_IN_PROGRESS: "Прогон review выполняется прямо сейчас",
    REASON_LESSONS_FLOWING: "Уроки создаются/проверяются в окне",
    REASON_APPLICATIONS_FLOWING: "Уроки применяются в окне",
    REASON_OUTCOMES_MEASURED: "Измеренные исходы появились в окне",
}

_TERMINAL_JOB_STATES = ("completed", "failed")


def _now(now: int | None) -> int:
    return int(time.time()) if now is None else int(now)


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _opt_ts(value):
    """0/мусор → None (честное «нет данных» вместо 1970)."""
    ts = _int(value)
    return ts if ts > 0 else None


def _row(row) -> dict:
    if row is None:
        return {}
    try:
        return dict(row)
    except (TypeError, ValueError):
        return {}


async def _fetch_all(db, sql: str, params=()) -> list[dict]:
    cursor = await db.db.execute(sql, params)
    return [_row(r) for r in await cursor.fetchall()]


async def _fetch_one(db, sql: str, params=()) -> dict:
    cursor = await db.db.execute(sql, params)
    return _row(await cursor.fetchone())


async def _window_counts(db, *, table: str, ts_col: str, now: int,
                         where: str = "", params=()) -> dict:
    """Счётчики строки-этапа: total + 24ч/7д/30д + максимум отметки времени.

    Один запрос на этап (SUM(CASE …)) — витрина не порождает лавину выборок.
    `where` — только внутренние константы модуля, не пользовательский ввод."""
    clause = f" WHERE {where}" if where else ""
    sql = (
        f"SELECT COUNT(*) AS total, MAX({ts_col}) AS last_ts, "
        f"SUM(CASE WHEN {ts_col} >= ? THEN 1 ELSE 0 END) AS w24, "
        f"SUM(CASE WHEN {ts_col} >= ? THEN 1 ELSE 0 END) AS w7, "
        f"SUM(CASE WHEN {ts_col} >= ? THEN 1 ELSE 0 END) AS w30 "
        f"FROM {table}{clause}"
    )
    row = await _fetch_one(
        db, sql, (now - WINDOW_24H, now - WINDOW_7D, now - WINDOW_30D,
                  *params))
    return {
        "total": _int(row.get("total")),
        "last_ts": _opt_ts(row.get("last_ts")),
        "windows": {"24h": _int(row.get("w24")),
                    "7d": _int(row.get("w7")),
                    "30d": _int(row.get("w30"))},
    }


async def _experience_events(db, *, chat_id: int | None,
                             now: int | None = None) -> dict[str, dict]:
    """Последняя строка и число событий по каждому имени (bounded).

    Счётчики — по окнам 24ч/7д/30д из тех же строк `mca_events`; отсутствие
    окна не подменяется нулём-догадкой (0 значит «в этом окне не было»)."""
    ts = _now(now)
    placeholders = ",".join("?" * len(EXPERIENCE_EVENT_NAMES))
    chat_clause = " AND chat_id = ?" if chat_id is not None else ""
    chat_params = (int(chat_id),) if chat_id is not None else ()
    try:
        last_rows = await _fetch_all(
            db,
            "SELECT event_name, ts, outcome, reason_code FROM mca_events "
            f"WHERE id IN (SELECT MAX(id) FROM mca_events WHERE event_name IN "
            f"({placeholders}){chat_clause} GROUP BY event_name)",
            (*EXPERIENCE_EVENT_NAMES, *chat_params))
        counts = await _fetch_all(
            db,
            "SELECT event_name, COUNT(*) AS c, "
            "SUM(CASE WHEN ts >= ? THEN 1 ELSE 0 END) AS w24, "
            "SUM(CASE WHEN ts >= ? THEN 1 ELSE 0 END) AS w7, "
            "SUM(CASE WHEN ts >= ? THEN 1 ELSE 0 END) AS w30 "
            f"FROM mca_events WHERE event_name IN ({placeholders}) "
            f"{chat_clause} GROUP BY event_name",
            (ts - WINDOW_24H, ts - WINDOW_7D, ts - WINDOW_30D,
             *EXPERIENCE_EVENT_NAMES, *chat_params))
    except Exception:
        logger.warning("[exp_diag] события опыта недоступны", exc_info=True)
        return {}
    by_name = {str(r.get("event_name")): r for r in counts}
    out: dict[str, dict] = {}
    for r in last_rows:
        name = str(r.get("event_name") or "")
        if not name:
            continue
        windows = by_name.get(name) or {}
        out[name] = {"last_ts": _opt_ts(r.get("ts")),
                     "last_outcome": r.get("outcome"),
                     "last_reason": r.get("reason_code"),
                     "count_window": _int(windows.get("w7")),
                     "windows": {"24h": _int(windows.get("w24")),
                                 "7d": _int(windows.get("w7")),
                                 "30d": _int(windows.get("w30"))}}
    for name, windows in by_name.items():
        out.setdefault(name, {"last_ts": None, "last_outcome": None,
                              "last_reason": None,
                              "count_window": _int(windows.get("w7")),
                              "windows": {"24h": _int(windows.get("w24")),
                                          "7d": _int(windows.get("w7")),
                                          "30d": _int(windows.get("w30"))}})
    return out


def _stage(*, key: str, enabled: bool, counters: dict,
           last_success_at=None, last_run_at=None,
           skip_reasons=None, reason: str = "",
           state: str | None = None, extra: dict | None = None) -> dict:
    """Собрать описание этапа (единый контракт для витрины)."""
    if state is None:
        state = _stage_state(enabled=enabled, counters=counters,
                             last_success_at=last_success_at,
                             last_run_at=last_run_at)
    skip = skip_reasons or []
    body = {
        "stage": key,
        "label": STAGE_LABELS.get(key, key),
        "enabled": bool(enabled),
        "state": state,
        "state_label": STATE_LABELS.get(state, state),
        "reason": reason,
        "reason_label": REASON_LABELS.get(reason, ""),
        "last_run_at": _opt_ts(last_run_at),
        "last_success_at": _opt_ts(last_success_at),
        "total": _int(counters.get("total")),
        "windows": dict(counters.get("windows") or {}),
        "skip_reasons": skip,
    }
    if extra:
        body.update(extra)
    return body


def _stage_state(*, enabled: bool, counters: dict, last_success_at,
                 last_run_at) -> str:
    """Состояние ОДНОГО этапа: disabled / never_run / working / idle."""
    if not enabled:
        return STATE_DISABLED
    if not _opt_ts(last_run_at) and not _int(counters.get("total")):
        return STATE_NEVER_RUN
    if _int((counters.get("windows") or {}).get("24h")) \
            or _int((counters.get("windows") or {}).get("7d")):
        return STATE_WORKING
    return STATE_IDLE


def _review_job_info(rows: list[dict]) -> dict:
    """Сводка durable review-джобы: активная, последний терминальный исход."""
    active = next((r for r in rows
                   if str(r.get("status")) in ("queued", "running")), None)
    terminal = [r for r in rows
                if str(r.get("status")) in _TERMINAL_JOB_STATES]
    last = terminal[0] if terminal else None
    return {
        "kind": "experience.review",
        "active": bool(active),
        "active_status": active.get("status") if active else None,
        "last_status": last.get("status") if last else None,
        "last_finished_at": _opt_ts((last or {}).get("finished_at"))
        or _opt_ts((last or {}).get("updated_at")),
        "last_error_code": (last or {}).get("error_code"),
        "last_reason_code": (last or {}).get("reason_code"),
    }


async def _review_jobs(db, *, limit: int = 20) -> list[dict]:
    try:
        return await _fetch_all(
            db,
            "SELECT job_id, status, reason_code, error_code, created_at, "
            "updated_at, finished_at, attempt, max_attempts FROM task_jobs "
            "WHERE kind = ? ORDER BY created_at DESC LIMIT ?",
            ("experience.review", max(1, int(limit))))
    except Exception:
        logger.warning("[exp_diag] task_jobs недоступен", exc_info=True)
        return []


def _lesson_counter_sums(rows: list[dict]) -> dict:
    """Суммы счётчиков уроков (только факт, без интерпретации)."""
    sums = {"success": 0, "failure": 0, "unknown": 0}
    for row in rows:
        sums["success"] += _int(row.get("counters_success"))
        sums["failure"] += _int(row.get("counters_failure"))
        sums["unknown"] += _int(row.get("counters_unknown"))
    return sums


def _lesson_status_counts(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "")
        if status:
            counts[status] = counts.get(status, 0) + 1
    return counts


def classify_experience_state(*, enabled: bool, cadence_seconds: int,
                              now: int, last_run_at, last_success_at,
                              last_error_at, learned_in_window: int,
                              applied_in_window: int, captured_in_window: int,
                              job_active: bool = False) -> dict:
    """Состояние цепочки по ФАКТИЧЕСКИМ отметкам (без догадок).

    Порядок решений важен и однозначен:
    выключено → нет прогонов → последний прогон с ошибкой → давно не
    запускалось → есть свежие результаты → простаивает (нет достойных уроков).
    «Ноль применений» само по себе НЕ делает цепочку сломанной: причины
    разбираются на уровне этапов."""
    stale_after = max(2 * max(1, int(cadence_seconds)), 2 * 3600)
    last_run = _opt_ts(last_run_at)
    last_ok = _opt_ts(last_success_at)
    last_err = _opt_ts(last_error_at)
    evidence = {"last_run_at": last_run, "last_success_at": last_ok,
                "last_error_at": last_err, "stale_after_seconds": stale_after,
                "learned_in_window": int(learned_in_window),
                "applied_in_window": int(applied_in_window),
                "captured_in_window": int(captured_in_window),
                "job_active": bool(job_active)}

    def _result(state: str, reason: str, detail: str = "") -> dict:
        return {"state": state, "state_label": STATE_LABELS.get(state, state),
                "reason": reason,
                "reason_label": REASON_LABELS.get(reason, detail),
                "evidence": evidence}

    if not enabled:
        return _result(STATE_DISABLED, REASON_DISABLED)
    if last_run is None and not job_active:
        return _result(STATE_NEVER_RUN, REASON_NO_REVIEW_RUNS)
    if job_active and last_run is None:
        return _result(STATE_NEVER_RUN, REASON_RUN_IN_PROGRESS)
    if last_err is not None and (last_ok is None or last_err >= last_ok):
        return _result(STATE_BROKEN, REASON_LAST_RUN_FAILED)
    if last_ok is None:
        return _result(STATE_NEVER_RUN, REASON_NO_REVIEW_RUNS)
    if (now - last_ok) > stale_after:
        return _result(STATE_STALE, REASON_NO_RECENT_RUNS)
    if applied_in_window > 0:
        return _result(STATE_WORKING, REASON_APPLICATIONS_FLOWING)
    if learned_in_window > 0:
        return _result(STATE_WORKING, REASON_LESSONS_FLOWING)
    if captured_in_window > 0:
        return _result(STATE_IDLE, REASON_NO_WORTHY_LESSONS)
    return _result(STATE_IDLE, REASON_NO_NEW_OBSERVATIONS)


def _application_reason(*, active_lessons: int, context_enabled: bool,
                        selection_runs: int, applications: int) -> str:
    """Почему применений нет (или есть) — по данным, а не по догадке."""
    if applications > 0:
        return REASON_APPLICATIONS_FLOWING
    if not context_enabled:
        return REASON_CONTEXT_OFF
    if active_lessons <= 0:
        return REASON_NO_ACTIVE_LESSONS
    if selection_runs <= 0:
        return REASON_NO_SELECTION_RUN
    return REASON_NOTHING_MATCHED


async def experience_pipeline_snapshot(db, *, now: int | None = None,
                                       chat_id: int | None = None,
                                       gates: dict | None = None) -> dict:
    """Полная диагностика цепочки опыта для scope (`global` или `chat:<id>`).

    Возвращает этапы, счётчики за 24ч/7д/30д и total, причины пропусков,
    состояние цепочки и словарь определений. Ничего не пишет."""
    ts = _now(now)
    scope_label = "global" if chat_id is None else f"chat:{int(chat_id)}"
    flags = gates or _gate_flags()
    cadence_name, cadence_seconds = _cadence()
    try:
        from services.mca_experience_jobs import learning_enabled_for_chat
        learning = bool(await learning_enabled_for_chat(chat_id))
    except Exception:
        learning = True
    enabled = bool(flags.get("lessons_enabled")
                   and flags.get("review_enabled") and learning)

    chat_where = "chat_id = ?" if chat_id is not None else ""
    chat_params = (int(chat_id),) if chat_id is not None else ()
    lesson_where = "scope_chat_id = ?" if chat_id is not None else ""
    lesson_params = (int(chat_id),) if chat_id is not None else ()

    try:
        episodes = await _window_counts(
            db, table="mca_experience_episodes", ts_col="created_at", now=ts,
            where=chat_where, params=chat_params)
    except Exception:
        logger.warning("[exp_diag] эпизоды опыта недоступны", exc_info=True)
        episodes = {"total": 0, "last_ts": None,
                    "windows": {"24h": 0, "7d": 0, "30d": 0}}
    try:
        feedback = await _window_counts(
            db, table="mca_experience_feedback", ts_col="ts", now=ts,
            where=chat_where, params=chat_params)
    except Exception:
        feedback = {"total": 0, "last_ts": None,
                    "windows": {"24h": 0, "7d": 0, "30d": 0}}

    lesson_rows: list[dict] = []
    application_rows: list[dict] = []
    try:
        lesson_rows = await _fetch_all(
            db,
            "SELECT lesson_id, version, type, scope, scope_chat_id, status, "
            "created_at, updated_at, last_validated_at, applications_count, "
            "counters_success, counters_failure, counters_unknown, "
            "recheck_required FROM mca_lessons"
            + (f" WHERE {lesson_where}" if lesson_where else ""),
            lesson_params)
    except Exception:
        logger.warning("[exp_diag] уроки недоступны", exc_info=True)
    try:
        application_rows = await _fetch_all(
            db,
            "SELECT application_id, lesson_id, lesson_version, applied_at, "
            "linked_at, outcome, measurement FROM mca_lesson_applications"
            + (f" WHERE {chat_where}" if chat_where else ""),
            chat_params)
    except Exception:
        logger.warning("[exp_diag] применения недоступны", exc_info=True)

    status_counts = _lesson_status_counts(lesson_rows)
    # Честное разделение: в chat-scope не входят уроки без chat-scope
    # (global/task без чата) — они видны отдельным числом, а не «схлопнуты».
    out_of_scope = 0
    if chat_id is not None:
        try:
            row = await _fetch_one(
                db, "SELECT COUNT(*) AS c FROM mca_lessons WHERE "
                "scope_chat_id IS NULL")
            out_of_scope = _int(row.get("c"))
        except Exception:
            out_of_scope = 0
    created_ts = [_opt_ts(r.get("created_at")) for r in lesson_rows]
    created_ts = [t for t in created_ts if t]
    validated_ts = [_opt_ts(r.get("last_validated_at")) for r in lesson_rows]
    validated_ts = [t for t in validated_ts if t]
    applied_ts = [_opt_ts(r.get("applied_at")) for r in application_rows]
    applied_ts = [t for t in applied_ts if t]
    linked_rows = [r for r in application_rows
                   if str(r.get("outcome") or "") in ("success", "failure")]

    def _windows(timestamps: list[int]) -> dict:
        return {
            "24h": sum(1 for t in timestamps if t >= ts - WINDOW_24H),
            "7d": sum(1 for t in timestamps if t >= ts - WINDOW_7D),
            "30d": sum(1 for t in timestamps if t >= ts - WINDOW_30D),
        }

    candidate_rows = [r for r in lesson_rows
                      if str(r.get("status")) == "candidate"]
    validated_rows = [r for r in lesson_rows
                      if str(r.get("status")) in ("validated", "active",
                                                   "suspended")]
    active_rows = [r for r in lesson_rows
                   if str(r.get("status")) == "active"]

    jobs = await _review_jobs(db)
    job_info = _review_job_info(jobs)
    events = await _experience_events(db, chat_id=chat_id, now=ts)

    def _event_ts(name: str):
        return _opt_ts((events.get(name) or {}).get("last_ts"))

    def _event_skip() -> list[dict]:
        rows: list[dict] = []
        for name, info in events.items():
            reason = info.get("last_reason")
            if not reason:
                continue
            rows.append({"event": name, "reason_code": reason,
                         "last_ts": _opt_ts(info.get("last_ts")),
                         "count_window": _int(info.get("count_window"))})
        rows.sort(key=lambda r: (-_int(r["count_window"]),
                                 -(r["last_ts"] or 0)))
        return rows[:12]

    last_run = job_info.get("last_finished_at") or _event_ts("lesson_proposed") \
        or _event_ts("experience_recorded")
    last_success = None if str(job_info.get("last_status") or "") == "failed" \
        else (job_info.get("last_finished_at")
              or _event_ts("experience_recorded"))
    last_error = (job_info.get("last_finished_at")
                  if str(job_info.get("last_status") or "") == "failed"
                  else None)

    counters_sums = _lesson_counter_sums(lesson_rows)
    unmeasured = [r for r in lesson_rows
                  if _int(r.get("applications_count")) > 0
                  and (_int(r.get("counters_success"))
                       + _int(r.get("counters_failure"))
                       + _int(r.get("counters_unknown"))) == 0]

    selection_runs = _int((events.get("retrieved") or {}).get("count_window"))
    application_reason = _application_reason(
        active_lessons=len(active_rows),
        context_enabled=bool(flags.get("context_enabled")),
        selection_runs=selection_runs,
        applications=len(application_rows))

    stages = {
        "observation": _stage(
            key="observation", enabled=enabled,
            counters={"total": episodes["total"] + feedback["total"],
                      "windows": {
                          "24h": episodes["windows"]["24h"]
                          + feedback["windows"]["24h"],
                          "7d": episodes["windows"]["7d"]
                          + feedback["windows"]["7d"],
                          "30d": episodes["windows"]["30d"]
                          + feedback["windows"]["30d"]}},
            last_run_at=max([t for t in (episodes["last_ts"],
                                         feedback["last_ts"]) if t],
                            default=None),
            last_success_at=max([t for t in (episodes["last_ts"],
                                             feedback["last_ts"]) if t],
                                default=None),
            skip_reasons=_event_skip(),
            reason=(REASON_NO_NEW_OBSERVATIONS
                    if not (episodes["windows"]["30d"]
                            or feedback["windows"]["30d"])
                    else ""),
            extra={"episodes": episodes, "feedback": feedback,
                   "semantic_event_last_at": _event_ts("experience_recorded")}),
        "candidate": _stage(
            key="candidate", enabled=enabled,
            counters={"total": status_counts.get("candidate", 0),
                      "windows": _windows(
                          [_opt_ts(r.get("created_at"))
                           for r in candidate_rows
                           if _opt_ts(r.get("created_at"))])},
            last_run_at=_event_ts("lesson_proposed"),
            last_success_at=max(created_ts, default=None),
            skip_reasons=_event_skip(),
            extra={"status_counts": status_counts,
                   "by_type": _by_type(lesson_rows),
                   "reason_codes": _lesson_reason_codes(events)}),
        "validation": _stage(
            key="validation", enabled=enabled,
            counters={"total": len(validated_rows),
                      "windows": _windows(validated_ts)},
            last_run_at=max([t for t in (_event_ts("validation_passed"),
                                         _event_ts("validation_failed")) if t],
                            default=None),
            last_success_at=max(validated_ts, default=None),
            skip_reasons=_event_skip(),
            extra={"passed_last_at": _event_ts("validation_passed"),
                   "failed_last_at": _event_ts("validation_failed"),
                   "last_failure_reason": (events.get("validation_failed")
                                           or {}).get("last_reason")}),
        "activation": _stage(
            key="activation", enabled=enabled,
            counters={"total": status_counts.get("active", 0),
                      "windows": _windows(
                          [_opt_ts(r.get("updated_at")) for r in active_rows
                           if _opt_ts(r.get("updated_at"))])},
            last_run_at=_event_ts("activated"),
            last_success_at=max([t for t in
                                 (_opt_ts(r.get("updated_at"))
                                  for r in active_rows) if t],
                                default=None),
            extra={"suspended": status_counts.get("suspended", 0),
                   "recheck_required": sum(
                       1 for r in lesson_rows
                       if _int(r.get("recheck_required")))}),
        "retrieval": _stage(
            key="retrieval", enabled=enabled
            and bool(flags.get("context_enabled")),
            counters={"total": selection_runs,
                      "windows": dict((events.get("retrieved") or {})
                                      .get("windows") or {})},
            last_run_at=_event_ts("retrieved"),
            last_success_at=_event_ts("retrieved"),
            reason=(REASON_CONTEXT_OFF
                    if not flags.get("context_enabled")
                    else REASON_NO_SELECTION_RUN if selection_runs <= 0
                    else ""),
            extra={"excluded_reasons": _retrieval_excluded(events)}),
        "application": _stage(
            key="application", enabled=enabled,
            counters={"total": len(application_rows),
                      "windows": _windows(applied_ts)},
            last_run_at=_event_ts("applied"),
            last_success_at=max(applied_ts, default=None),
            reason=application_reason,
            extra={"unique_lessons": len({str(r.get("lesson_id"))
                                          for r in application_rows}),
                   "active_lessons": len(active_rows),
                   "selection_runs_7d": selection_runs}),
        "outcome": _stage(
            key="outcome", enabled=enabled,
            counters={"total": len(linked_rows),
                      "windows": _windows(
                          [_opt_ts(r.get("linked_at")) for r in linked_rows
                           if _opt_ts(r.get("linked_at"))])},
            last_run_at=max([t for t in
                             (_opt_ts(r.get("linked_at"))
                              for r in linked_rows) if t], default=None),
            last_success_at=max([t for t in
                                 (_opt_ts(r.get("linked_at"))
                                  for r in linked_rows) if t], default=None),
            reason=("" if linked_rows else REASON_NO_APPLICATIONS),
            extra={"counters": counters_sums,
                   "applications_unknown": len(application_rows)
                   - len(linked_rows)}),
        "utility": _stage(
            key="utility", enabled=enabled,
            counters={"total": len(unmeasured), "windows": {}},
            last_run_at=_event_ts("utility_updated"),
            last_success_at=_event_ts("utility_updated"),
            reason=("" if not unmeasured else REASON_NO_APPLICATIONS),
            extra={"applications_without_outcome": len(unmeasured)}),
    }

    classification = classify_experience_state(
        enabled=enabled, cadence_seconds=cadence_seconds, now=ts,
        last_run_at=last_run, last_success_at=last_success,
        last_error_at=last_error,
        learned_in_window=sum(1 for t in created_ts if t >= ts - WINDOW_24H),
        applied_in_window=sum(1 for t in applied_ts if t >= ts - WINDOW_24H),
        captured_in_window=(episodes["windows"]["24h"]
                            + feedback["windows"]["24h"]),
        job_active=bool(job_info.get("active")))

    return {
        "scope": scope_label,
        "chat_id": None if chat_id is None else int(chat_id),
        "generated_at": ts,
        "enabled": enabled,
        "gates": dict(flags),
        "cadence": {"name": cadence_name,
                    "seconds": cadence_seconds},
        "state": classification["state"],
        "state_label": classification["state_label"],
        "reason": classification["reason"],
        "reason_label": classification["reason_label"],
        "evidence": classification["evidence"],
        "job": job_info,
        "stages": stages,
        "order": list(PIPELINE_STAGES),
        "definitions": {
            "states": dict(STATE_LABELS),
            "reasons": dict(REASON_LABELS),
            "windows_seconds": {"24h": WINDOW_24H, "7d": WINDOW_7D,
                                "30d": WINDOW_30D},
            "note": ("total — все строки за всё время; windows — только "
                     "строки с отметкой времени в окне. Разные классы "
                     "(candidate/validated/active) не обязаны совпадать."),
        },
        "counters": {"lessons": status_counts,
                     "lesson_counters": counters_sums,
                     "applications_total": len(application_rows),
                     "lessons_out_of_chat_scope": out_of_scope},
    }


def _by_type(lesson_rows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in lesson_rows:
        key = str(row.get("type") or "")
        if key:
            out[key] = out.get(key, 0) + 1
    return out


def _lesson_reason_codes(events: dict[str, dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in ("lesson_proposed", "validation_failed", "suspended",
                 "superseded"):
        reason = (events.get(name) or {}).get("last_reason")
        if reason:
            out[name] = str(reason)
    return out


def _retrieval_excluded(events: dict[str, dict]) -> list[dict]:
    """Причины исключения уроков из отбора — из событий отбора.

    Отбор эмитит `retrieved` только при успехе; причины пропуска приходят
    кодами отбора внутри payload события `retrieved`. Если событий нет —
    пустой список (честное «неизвестно»), а не выдуманные причины."""
    rows: list[dict] = []
    info = events.get("retrieved") or {}
    reason = info.get("last_reason")
    if reason:
        rows.append({"reason_code": str(reason),
                     "last_ts": _opt_ts(info.get("last_ts"))})
    return rows


async def experience_pipeline_reasons(db, *, now: int | None = None,
                                      chat_id: int | None = None,
                                      limit: int = 20) -> dict:
    """Причины по этапам за 7 дней (раскрываемая деталь витрины).

    Источник — типизированные события контура опыта; при отсутствии событий
    честно возвращается пустой список, а не «причина по умолчанию»."""
    ts = _now(now)
    events = await _experience_events(db, chat_id=chat_id, now=ts)
    items: list[dict] = []
    for name, info in events.items():
        items.append({"event": name,
                      "count_window": _int(info.get("count_window")),
                      "windows": dict(info.get("windows") or {}),
                      "last_ts": _opt_ts(info.get("last_ts")),
                      "last_outcome": info.get("last_outcome"),
                      "last_reason": info.get("last_reason")})
    items.sort(key=lambda r: (-_int(r["count_window"]),
                              -(r["last_ts"] or 0)))
    return {"scope": "global" if chat_id is None else f"chat:{int(chat_id)}",
            "generated_at": ts, "window_seconds": WINDOW_7D,
            "items": items[:max(1, int(limit))]}


def _gate_flags() -> dict:
    """Ключевые гейты контура (fail-open: только чтение настроек)."""
    try:
        from services import mca_gates
        return {
            "lessons_enabled": bool(mca_gates.experience_lessons_enabled()),
            "review_enabled": bool(mca_gates.experience_review_enabled()),
            "context_enabled": bool(mca_gates.experience_context_enabled()),
            "feedback_enabled": bool(mca_gates.experience_feedback_enabled()),
        }
    except Exception:
        return {"lessons_enabled": True, "review_enabled": True,
                "context_enabled": True, "feedback_enabled": True}


def _cadence() -> tuple[str, int]:
    """Каденция review из существующих настроек (hot; без второго каталога)."""
    try:
        from services import mca_experience_jobs as jobs
        name = str(jobs.review_cadence() or "daily")
        return name, int(jobs.CADENCE_SECONDS.get(name, 86400))
    except Exception:
        return "daily", 86400
