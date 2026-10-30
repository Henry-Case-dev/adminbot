"""EVOL-020 — «Опыт»: жива ли цепочка и что реально означают показатели.

TEST-LIFECYCLE: CONTRACT (plans/current_task.md EVOL-020).

Проверяется честность диагностики: состояния `working` / `idle` / `broken` /
`disabled` / `stale` различаются, счётчики привязаны к окнам, причины «ноль
применений» выводятся из данных, уроки/применения не фабрикуются, два чата
не смешиваются. Сети/LLM нет — только существующие durable-таблицы.
"""
import json
import time

import pytest

from services import mca_events
from services import mca_experience as me
from services.database import DatabaseService
from services.experience_diagnostics import (
    REASON_APPLICATIONS_FLOWING,
    REASON_APPLICATIONS_NOT_IN_WINDOW,
    REASON_CONTEXT_OFF,
    REASON_LESSONS_PROPOSED_ONLY,
    REASON_NOTHING_MATCHED,
    REASON_NO_APPLICATIONS,
    REASON_NO_REVIEW_RUNS,
    REASON_NO_SELECTION_RUN,
    REASON_NO_WORTHY_LESSONS,
    REASON_OUTCOME_NOT_MEASURED,
    REASON_SELECTION_EMPTY,
    STATE_BROKEN,
    STATE_DISABLED,
    STATE_IDLE,
    STATE_NEVER_RUN,
    STATE_STALE,
    STATE_WORKING,
    experience_pipeline_reasons,
    experience_pipeline_snapshot,
)

NOW = int(time.time())
DAY = 86400

ALL_ON = {"lessons_enabled": True, "review_enabled": True,
          "context_enabled": True, "feedback_enabled": True}


async def _db():
    svc = DatabaseService(":memory:")
    await svc.initialize()
    return svc


async def _episode(db, chat_id, ts, outcome="unknown"):
    await db.db.execute(
        "INSERT INTO mca_experience_episodes (episode_id, idempotency_key, "
        "created_at, updated_at, scope, chat_id, outcome_kind, outcome_source, "
        "outcome_reliability) VALUES (?, ?, ?, ?, 'chat', ?, ?, 'technical', "
        "'weak')",
        (f"ep-{chat_id}-{ts}", f"idem-{chat_id}-{ts}", ts, ts, chat_id,
         outcome))
    await db.db.commit()


async def _lesson(db, *, lesson_id="l-1", status="active", chat_id=-100,
                  created_at=NOW - 3600, validated_at=None,
                  applications=0, success=0, failure=0, unknown=0,
                  last_validated_at=None):
    await db.db.execute(
        "INSERT INTO mca_lessons (lesson_id, version, type, scope, "
        "scope_chat_id, recommendation, status, recheck_required, historical, "
        "unverified, last_validated_at, counters_success, counters_failure, "
        "counters_unknown, applications_count, created_at, updated_at) "
        "VALUES (?, 1, 'tool_usage', 'chat', ?, 'canon', ?, 0, 0, 0, ?, ?, ?, "
        "?, ?, ?, ?)",
        (lesson_id, chat_id, status, last_validated_at, success, failure,
         unknown, applications, created_at, created_at))
    await db.db.commit()


async def _application(db, *, lesson_id="l-1", chat_id=-100,
                       applied_at=NOW - 1800, outcome="unknown",
                       linked_at=None):
    await db.db.execute(
        "INSERT INTO mca_lesson_applications (dedup_key, lesson_id, "
        "lesson_version, application_ref, chat_id, applied_at, outcome, "
        "linked_at) VALUES (?, ?, 1, ?, ?, ?, ?, ?)",
        (f"dk-{lesson_id}-{applied_at}", lesson_id, f"ref-{applied_at}",
         chat_id, applied_at, outcome, linked_at))
    await db.db.commit()


async def _job(db, status, finished_at, *, error_code=None, chat_id=None):
    await db.db.execute(
        "INSERT INTO task_jobs (job_id, owner, kind, payload, status, "
        "error_code, attempt, max_attempts, created_at, updated_at, "
        "finished_at) VALUES (?, 'mca16', 'experience.review', '{}', ?, ?, 1, "
        "3, ?, ?, ?)",
        (f"job-{status}-{finished_at}", status, error_code,
         finished_at - 60, finished_at, finished_at))
    await db.db.commit()


async def _event(db, name, ts, outcome="success", reason=None,
                 chat_id=None, payload=None):
    await db.db.execute(
        "INSERT INTO mca_events (ts, level, event_name, outcome, chat_id, "
        "reason_code, usage_json) VALUES (?, 'INFO', ?, ?, ?, ?, ?)",
        (ts, name, outcome, chat_id, reason,
         None if payload is None else json.dumps(payload)))
    await db.db.commit()


async def _current_compat(db, lesson_id):
    """Сделать урок совместимым с текущим окружением (иначе отбор его
    исключает как `stale_context`, а не по релевантности)."""
    await db.db.execute(
        "UPDATE mca_lessons SET compat_tool_schema_hash = ?, "
        "compat_model_fingerprint = ?, compat_config_version = ? "
        "WHERE lesson_id = ?",
        (me.current_tool_schema_hash(), me.current_model_fingerprint(),
         me.current_config_version(), lesson_id))
    await db.db.commit()


@pytest.mark.asyncio
async def test_disabled_state_never_claims_work():
    db = await _db()
    try:
        await _episode(db, -100, NOW - 600)
        body = await experience_pipeline_snapshot(
            db, now=NOW, chat_id=-100,
            gates={**ALL_ON, "lessons_enabled": False})
        assert body["state"] == STATE_DISABLED
        assert body["state_label"]
        assert body["enabled"] is False
        for stage in body["stages"].values():
            assert stage["state"] == STATE_DISABLED
            assert stage["state_label"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_never_run_differs_from_idle():
    db = await _db()
    try:
        body = await experience_pipeline_snapshot(
            db, now=NOW, chat_id=-100, gates=ALL_ON)
        assert body["state"] == STATE_NEVER_RUN
        assert body["reason"] == REASON_NO_REVIEW_RUNS
        assert body["stages"]["observation"]["state"] == STATE_NEVER_RUN
        assert body["job"]["last_status"] is None
        assert body["stages"]["observation"]["windows"] == {
            "24h": 0, "7d": 0, "30d": 0}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_idle_means_runs_but_no_worthy_lessons():
    db = await _db()
    try:
        await _job(db, "completed", NOW - 3600)
        await _episode(db, -100, NOW - 1200)
        await _episode(db, -100, NOW - 2400)
        body = await experience_pipeline_snapshot(
            db, now=NOW, chat_id=-100, gates=ALL_ON)
        assert body["state"] == STATE_IDLE
        assert body["reason"] == REASON_NO_WORTHY_LESSONS
        assert body["stages"]["observation"]["windows"]["24h"] == 2
        assert body["stages"]["candidate"]["total"] == 0
        # «Нет достойных уроков» — не ошибка: job не failed.
        assert body["job"]["last_status"] == "completed"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_working_state_from_real_rows_and_honest_counters():
    db = await _db()
    try:
        await _job(db, "completed", NOW - 1800)
        await _lesson(db, lesson_id="l-new", status="active",
                      created_at=NOW - 900, applications=1)
        await _application(db, lesson_id="l-new", applied_at=NOW - 600,
                           outcome="success", linked_at=NOW - 300)
        body = await experience_pipeline_snapshot(
            db, now=NOW, chat_id=-100, gates=ALL_ON)
        assert body["state"] == STATE_WORKING
        assert body["reason"] == REASON_APPLICATIONS_FLOWING
        assert body["stages"]["application"]["windows"]["24h"] == 1
        assert body["stages"]["outcome"]["windows"]["24h"] == 1
        assert body["counters"]["lessons"]["active"] == 1
        assert body["counters"]["applications_total"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_broken_when_last_run_failed():
    db = await _db()
    try:
        await _job(db, "completed", NOW - 3 * DAY)
        await _job(db, "failed", NOW - 3600, error_code="timeout")
        body = await experience_pipeline_snapshot(
            db, now=NOW, chat_id=-100, gates=ALL_ON)
        assert body["state"] == STATE_BROKEN
        assert body["job"]["last_status"] == "failed"
        assert body["evidence"]["last_error_at"] == NOW - 3600
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_stale_when_no_runs_for_two_cadences():
    db = await _db()
    try:
        await _job(db, "completed", NOW - 5 * DAY)
        body = await experience_pipeline_snapshot(
            db, now=NOW, chat_id=-100, gates=ALL_ON)
        assert body["state"] == STATE_STALE
        assert body["cadence"]["name"] == "daily"
        assert body["evidence"]["stale_after_seconds"] >= 2 * DAY - 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_windows_and_total_are_explained_not_faked():
    db = await _db()
    try:
        await _job(db, "completed", NOW - 1800)
        await _lesson(db, lesson_id="l-recent", status="candidate",
                      created_at=NOW - 2 * DAY)
        await _lesson(db, lesson_id="l-old", status="candidate",
                      created_at=NOW - 40 * DAY)
        body = await experience_pipeline_snapshot(
            db, now=NOW, chat_id=-100, gates=ALL_ON)
        candidate = body["stages"]["candidate"]
        assert candidate["total"] == 2
        assert candidate["windows"] == {"24h": 0, "7d": 1, "30d": 1}
        assert body["definitions"]["note"]
        # Состояние не «работает» от старых строк: в 24ч уроков не было.
        assert body["state"] == STATE_IDLE
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_zero_applications_has_a_data_backed_reason():
    db = await _db()
    try:
        await _job(db, "completed", NOW - 1800)
        await _lesson(db, lesson_id="l-active", status="active",
                      created_at=NOW - 900)
        body = await experience_pipeline_snapshot(
            db, now=NOW, chat_id=-100, gates=ALL_ON)
        application = body["stages"]["application"]
        assert application["total"] == 0
        assert application["reason"] == REASON_NO_SELECTION_RUN
        assert "не запускался" in application["reason_label"]
        # Никаких выдуманных применений ради красивой витрины.
        assert body["counters"]["applications_total"] == 0

        off = await experience_pipeline_snapshot(
            db, now=NOW, chat_id=-100,
            gates={**ALL_ON, "context_enabled": False})
        assert off["stages"]["application"]["reason"] == REASON_CONTEXT_OFF
        assert off["stages"]["retrieval"]["state"] == STATE_DISABLED
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_no_active_lessons_is_not_an_error():
    db = await _db()
    try:
        await _job(db, "completed", NOW - 1800)
        await _lesson(db, lesson_id="l-cand", status="candidate",
                      created_at=NOW - 900)
        body = await experience_pipeline_snapshot(
            db, now=NOW, chat_id=-100, gates=ALL_ON)
        application = body["stages"]["application"]
        assert application["reason"] == "no_active_lessons"
        assert "не ошибка" in application["reason_label"]
        assert body["state"] != STATE_BROKEN
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_two_chats_are_isolated():
    db = await _db()
    try:
        await _job(db, "completed", NOW - 600)
        await _lesson(db, lesson_id="l-a", chat_id=-100,
                      created_at=NOW - 600)
        await _lesson(db, lesson_id="l-b", chat_id=-200,
                      created_at=NOW - 600)
        await _episode(db, -100, NOW - 300)
        await _episode(db, -200, NOW - 300)
        await _episode(db, -200, NOW - 400)
        first = await experience_pipeline_snapshot(
            db, now=NOW, chat_id=-100, gates=ALL_ON)
        second = await experience_pipeline_snapshot(
            db, now=NOW, chat_id=-200, gates=ALL_ON)
        assert first["scope"] == "chat:-100"
        assert second["scope"] == "chat:-200"
        assert first["stages"]["observation"]["windows"]["24h"] == 1
        assert second["stages"]["observation"]["windows"]["24h"] == 2
        assert first["counters"]["lessons"] == {"active": 1}
        assert second["counters"]["lessons"] == {"active": 1}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_diagnostics_do_not_create_lessons_or_applications():
    db = await _db()
    try:
        await _job(db, "completed", NOW - 1800)
        await _episode(db, -100, NOW - 600)
        before = (await _count(db, "mca_lessons"),
                  await _count(db, "mca_lesson_applications"),
                  await _count(db, "mca_experience_episodes"))
        await experience_pipeline_snapshot(db, now=NOW, chat_id=-100,
                                           gates=ALL_ON)
        await experience_pipeline_reasons(db, now=NOW, chat_id=-100)
        after = (await _count(db, "mca_lessons"),
                 await _count(db, "mca_lesson_applications"),
                 await _count(db, "mca_experience_episodes"))
        assert before == after
    finally:
        await db.close()


async def _count(db, table):
    cursor = await db.db.execute(f"SELECT COUNT(*) AS c FROM {table}")
    return int((await cursor.fetchone())["c"])


@pytest.mark.asyncio
async def test_reasons_surface_skip_codes_from_events():
    db = await _db()
    try:
        await _event(db, "validation_failed", NOW - 600, outcome="failed",
                     reason="insufficient_evidence", chat_id=-100)
        await _event(db, "lesson_proposed", NOW - 900, chat_id=-100)
        body = await experience_pipeline_reasons(db, now=NOW, chat_id=-100)
        items = {i["event"]: i for i in body["items"]}
        assert items["validation_failed"]["last_reason"] == \
            "insufficient_evidence"
        assert items["validation_failed"]["windows"]["24h"] == 1
        assert body["window_seconds"] == 7 * DAY
    finally:
        await db.close()


# ═══ review-fix: три блокера витрины «Опыт» ═══════════════════════════════


@pytest.mark.asyncio
async def test_candidates_without_validation_are_idle_not_working():
    """B1: «работает» нельзя выводить из одних предложенных кандидатов.

    Сценарий ревью: 2 кандидата (проверка не запускалась), 5 эпизодов,
    review-job завершён 30 минут назад. Раньше цепочка показывала working /
    «уроки создаются/проверяются в окне» при validation/activation/application
    = never_run и 0 применений."""
    db = await _db()
    try:
        await _job(db, "completed", NOW - 1800)
        await _lesson(db, lesson_id="l-cand-1", status="candidate",
                      created_at=NOW - 900)
        await _lesson(db, lesson_id="l-cand-2", status="candidate",
                      created_at=NOW - 1200)
        for index in range(5):
            await _episode(db, -100, NOW - 300 - index * 60)
        body = await experience_pipeline_snapshot(
            db, now=NOW, chat_id=-100, gates=ALL_ON)
        assert body["state"] == STATE_IDLE
        assert body["state"] != STATE_WORKING
        assert body["reason"] == REASON_LESSONS_PROPOSED_ONLY
        label = body["reason_label"]
        assert "предложены" in label
        assert "ещё не проходила" in label
        # Подпись не должна обещать проверку, которой не было.
        assert "проверяются" not in label
        assert body["stages"]["candidate"]["total"] == 2
        for stage in ("validation", "activation", "retrieval", "application"):
            assert body["stages"][stage]["state"] == STATE_NEVER_RUN, stage
        assert body["stages"]["application"]["windows"]["24h"] == 0
        assert body["evidence"]["validated_in_window"] == 0
        assert body["evidence"]["activated_in_window"] == 0
        assert body["evidence"]["proposed_in_window"] == 2
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_validated_lesson_without_activation_is_working_but_not_activated():
    """B1 (обратная сторона): подтверждённая проверка — уже не «простаивает».

    Проверка прошла в окне, активации нет → `working` с честной причиной
    «проверены, активации пока не было», а не «применяются».
    """
    db = await _db()
    try:
        await _job(db, "completed", NOW - 1800)
        await _lesson(db, lesson_id="l-val", status="validated",
                      created_at=NOW - 900, last_validated_at=NOW - 600)
        body = await experience_pipeline_snapshot(
            db, now=NOW, chat_id=-100, gates=ALL_ON)
        assert body["state"] == STATE_WORKING
        assert body["reason"] == "lessons_validated"
        assert body["reason"] != REASON_APPLICATIONS_FLOWING
        assert "проверку" in body["reason_label"]
        assert body["evidence"]["validated_in_window"] == 1
        assert body["evidence"]["activated_in_window"] == 0
        assert body["stages"]["activation"]["total"] == 0
        assert body["stages"]["application"]["windows"]["24h"] == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_application_reason_is_windowed_and_outcome_is_separate():
    """B2: причина применения — по окну, а «исход не измерен» — отдельно.

    Сценарий ревью: одно применение 40 дней назад (total=1, окна нулевые).
    Раньше этап заявлял applications_flowing, а outcome/utility — что
    «применений не записывалось», хотя строка применения есть."""
    db = await _db()
    try:
        await _job(db, "completed", NOW - 1800)
        await _lesson(db, lesson_id="l-old", status="active",
                      created_at=NOW - 40 * DAY, applications=1)
        await _application(db, lesson_id="l-old", applied_at=NOW - 40 * DAY,
                           outcome="unknown")
        body = await experience_pipeline_snapshot(
            db, now=NOW, chat_id=-100, gates=ALL_ON)
        application = body["stages"]["application"]
        assert application["total"] == 1
        assert application["windows"] == {"24h": 0, "7d": 0, "30d": 0}
        assert application["reason"] == REASON_APPLICATIONS_NOT_IN_WINDOW
        assert application["reason"] != REASON_APPLICATIONS_FLOWING
        assert "раньше" in application["reason_label"]
        # Старая строка не делает цепочку зелёной.
        assert body["state"] != STATE_WORKING
        outcome = body["stages"]["outcome"]
        assert outcome["total"] == 0
        assert outcome["reason"] == REASON_OUTCOME_NOT_MEASURED
        assert outcome["reason"] != REASON_NO_APPLICATIONS
        assert "не измерен" in outcome["reason_label"]
        utility = body["stages"]["utility"]
        assert utility["total"] == 1
        assert utility["reason"] == REASON_OUTCOME_NOT_MEASURED
        assert "не записывались" not in utility["reason_label"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_empty_selection_counts_as_run_not_as_never_run():
    """B3: отбор запускался, но ничего не прошло — это не «не запускался».

    Реальный путь: активный урок есть, запрос нерелевантен → отбор возвращает
    `retrieval_empty`. Событие отбора должно дойти до `mca_events`, попасть в
    счётчик прогонов и объяснить исключение по коду."""
    db = await _db()
    try:
        await _job(db, "completed", NOW - 1800)
        await _lesson(db, lesson_id="l-rel", status="active",
                      created_at=NOW - 900)
        await _current_compat(db, "l-rel")
        svc = me.get_service(db)
        result = await svc.lesson.select_for_context(
            chat_id=-100, user_id=7,
            query="совершенно другая тема: погода и отпуск")
        assert result.lessons == ()
        assert result.reason_code == "retrieval_empty"
        assert result.excluded
        assert result.excluded[0]["reason_code"] == "no_relevant_memory"
        # Никаких выдуманных уроков/применений.
        assert await _count(db, "mca_lesson_applications") == 0
        assert await mca_events.flush_events(db) >= 1

        body = await experience_pipeline_snapshot(
            db, now=NOW, chat_id=-100, gates=ALL_ON)
        retrieval = body["stages"]["retrieval"]
        assert retrieval["state"] == STATE_IDLE
        assert retrieval["state"] != STATE_NEVER_RUN
        assert retrieval["reason"] == REASON_SELECTION_EMPTY
        assert "отбор" in retrieval["reason_label"].lower()
        assert retrieval["total"] == 1
        assert retrieval["selected_runs_7d"] == 0
        assert retrieval["empty_runs_7d"] == 1
        assert retrieval["last_selection_outcome"] == "skipped"
        codes = {row["reason_code"]
                 for row in retrieval["excluded_reasons"]}
        assert "no_relevant_memory" in codes
        # Причина применения больше не «отбор ни разу не запускался».
        application = body["stages"]["application"]
        assert application["reason"] != REASON_NO_SELECTION_RUN
        assert application["reason"] == REASON_NOTHING_MATCHED
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_selection_failure_is_not_reported_as_nothing_matched():
    """B3 (край): сбой чтения кандидатов — прогон, но не «ничего не прошло»."""
    db = await _db()
    try:
        await _job(db, "completed", NOW - 1800)
        await _event(db, "retrieved", NOW - 600, outcome="failed",
                     reason="retrieval_empty", chat_id=-100)
        body = await experience_pipeline_snapshot(
            db, now=NOW, chat_id=-100, gates=ALL_ON)
        retrieval = body["stages"]["retrieval"]
        assert retrieval["state"] == STATE_IDLE
        assert retrieval["reason"] == "selection_failed"
        assert retrieval["failed_runs_7d"] == 1
        assert retrieval["empty_runs_7d"] == 0
    finally:
        await db.close()
