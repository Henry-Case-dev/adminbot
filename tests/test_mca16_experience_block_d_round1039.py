"""MCA-16 `mca-16-experience-lessons` — focused-тесты блока D (T-5003/T-5004).

Покрытие:
  * review — отдельный тип job в СУЩЕСТВУЮЩЕЙ очереди (kind/owner/coalesce,
    singleflight, durable counters/checkpoint);
  * capture-cursor из типизированных источников (feedback + tool_call
    notable-терминалы mca-11) — bounded batch, идемпотентность;
  * propose/validate/activate — детерминированные канонические правила;
  * на каждое сообщение LLM-рефлексии НЕТ (в модуле нет LLM-клиента);
  * deep sleep не смешивает lessons с парадигмами (отдельный kind/сущности);
  * случайность — только существующий журнал mca_random_draws как наблюдение;
    второго RandomSource/процента нет; истинность/успех не рандомизируются;
  * outcome-link/utility: только применённые уроки, только независимый
    проверенный исход ПОЗЖЕ применения; unknown не обновляет; `utility_updated`
    агрегирован на запуск;
  * prune retention с защитой связанного с уроками/feedback;
  * дедуп/рестарт: повторный прогон не плодит уроки;
  * OFF-паритет K1/K3 (job не запускается).
"""
import json
import pathlib

import pytest

from services import mca_events, mca_gates
from services import mca_experience as me
from services import mca_experience_jobs as mj
from services.database import DatabaseService
from services.mca_retrieval_context import LessonRef
from services.task_supervisor import TaskJobStore


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


async def _db(tmp_path, name="mca16_d.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _insert_tool_failure(db, *, event_id=None, chat_id=-100, tool="web",
                               trace_id="tr-1", ts=1000):
    entity = json.dumps({"tool": tool, "args_fingerprint": "fp"})
    await db.db.execute(
        "INSERT INTO mca_events (ts, level, event_name, outcome, trace_id, "
        "chat_id, component, stage, reason_code, entity_ids) VALUES "
        "(?, 'WARNING', 'tool_call', 'failed', ?, ?, 'tools', 'execute', "
        "'timeout', ?)", (int(ts), str(trace_id), int(chat_id), entity))
    await db.db.commit()


async def _insert_draw(db, *, draw_id="d1", chat_id=-100):
    await db.db.execute(
        "INSERT INTO mca_random_draws (draw_id, created_at, chat_id, purpose, "
        "source, selected_id, fallback_reason, value) VALUES "
        "(?, 1000, ?, 'exploration', 'pseudorandom', '2', NULL, 0.5)",
        (str(draw_id), int(chat_id)))
    await db.db.commit()


def _jobs_src() -> str:
    return pathlib.Path(mj.__file__).read_text(encoding="utf-8")


# ═══ T-5003: job-тип, очередь, singleflight ═════════════════════════════════

@pytest.mark.asyncio
async def test_job_kind_owner_coalesce_and_singleflight(tmp_path):
    db = await _db(tmp_path)
    try:
        j1 = await mj.enqueue_experience_review(db)
        j2 = await mj.enqueue_experience_review(db)
        assert j1 and j2 and j1 == j2          # singleflight: один активный
        row = await TaskJobStore(db).get(j1)
        assert row["kind"] == "experience.review"
        assert row["owner"] == "mca16"
        assert row["coalesce_key"] == "experience.review:global"
        assert row["status"] == "queued"
        payload = json.loads(row["payload"])
        assert payload["counters"]["proposed"] == 0
        assert mj.review_coalesce_key() == "experience.review:global"
        active = await mj.get_active_review(db)
        assert active["job_id"] == j1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_off_parity_k1_k3_job_not_started(tmp_path, monkeypatch):
    db = await _db(tmp_path)
    try:
        monkeypatch.setattr(mca_gates, "experience_review_enabled",
                            lambda: False)
        assert await mj.enqueue_experience_review(db) is None
        assert await mj.tick_experience_review(db) == "disabled"
        monkeypatch.setattr(mca_gates, "experience_review_enabled",
                            lambda: True)
        monkeypatch.setattr(mca_gates, "experience_lessons_enabled",
                            lambda: False)
        assert await mj.enqueue_experience_review(db) is None
        assert await mj.tick_experience_review(db) == "disabled"
        assert await mj.get_active_review(db) is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_correction_triggers_enqueue_only_meaningful(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        await svc.record_feedback(source_kind="social_reaction",
                                  chat_id=-100, ref_type="message", ref_id=1)
        assert await mj.get_active_review(db) is None
        await svc.record_feedback(source_kind="owner_correction",
                                  chat_id=-100, ref_type="message", ref_id=2)
        active = await mj.get_active_review(db)
        assert active is not None and active["kind"] == "experience.review"
    finally:
        await db.close()


# ═══ capture-cursor + propose/validate/activate ═════════════════════════════

@pytest.mark.asyncio
async def test_tool_failures_capture_propose_activate(tmp_path):
    db = await _db(tmp_path)
    try:
        for i in range(3):
            await _insert_tool_failure(db, chat_id=-100, tool="web_search",
                                       trace_id=f"t-{i}", ts=1000 + i)
        status = await mj.tick_experience_review(db)
        assert status == "completed"
        svc = me.get_service(db)
        lessons = await svc.list_lessons(chat_id=-100)
        assert len(lessons) == 1
        lesson = lessons[0]
        assert lesson["type"] == "tool_usage"
        assert lesson["status"] == "active"
        assert lesson["scope"] == "chat"
        assert lesson["applicability"] == "tool:web_search"
        assert lesson["recommendation"] == me.CANONICAL_RECOMMENDATIONS[
            ("tool_usage", "retry_after_typed_failure")]
        assert lesson["validator_version"] == me.VALIDATOR_VERSION
        # основания — три независимых эпизода (mca-04a derived_from)
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_evidence_links WHERE "
            "subject_ref_id = ? AND link_type = 'derived_from'",
            (lesson["source_ref_id"],))
        assert (await cursor.fetchone())["c"] == 3
        assert await svc.store.count("mca_experience_episodes") == 3
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_capture_cursor_bounded_batches(tmp_path, monkeypatch):
    db = await _db(tmp_path)
    try:
        monkeypatch.setattr(mca_gates, "experience_review_batch_max",
                            lambda: 2)
        for i in range(5):
            await _insert_tool_failure(db, trace_id=f"b-{i}", ts=1000 + i)
        assert await mj.tick_experience_review(db) == "completed"
        assert await me.get_service(db).store.count(
            "mca_experience_episodes") == 2
        # второй прогон: следующая порция (durable cursor), не всё сразу
        await db.db.execute(
            "UPDATE task_jobs SET status = 'completed', finished_at = 0 "
            "WHERE kind = ?",
            ("experience.review",))
        await db.db.commit()
        assert await mj.tick_experience_review(db) == "completed"
        assert await me.get_service(db).store.count(
            "mca_experience_episodes") == 4
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_feedback_capture_and_correction_lesson(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        for i in range(3):
            await svc.record_feedback(
                source_kind="owner_correction", chat_id=-100,
                ref_type="message", ref_id=100 + i, trace_id=f"c-{i}",
                signal={"code": "count_fix"})
        # enqueue при коррекции уже создан; прогон тика доводит до урока
        assert await mj.tick_experience_review(db) == "completed"
        lessons = await svc.list_lessons(chat_id=-100)
        assert len(lessons) == 1
        lesson = lessons[0]
        assert lesson["type"] == "failure_pattern"
        assert lesson["status"] == "active"
        episodes = await svc.store.find_episodes_by_ref(
            -100, trace_id="c-0")
        assert episodes and episodes[0]["outcome_kind"] == "failure"
        assert episodes[0]["outcome_source"] == "explicit"
        assert episodes[0]["outcome_reliability"] == "verified"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_preference_signal_scoped_user_in_chat(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        await svc.record_feedback(
            source_kind="participant_correction", chat_id=-100,
            ref_type="message", ref_id=7,
            signal={"preference": "short_answers", "user_id": 7})
        assert await mj.tick_experience_review(db) == "completed"
        lessons = await svc.list_lessons(chat_id=-100)
        assert len(lessons) == 1
        lesson = lessons[0]
        assert lesson["type"] == "social_preference"
        assert lesson["scope"] == "user_in_chat"
        assert lesson["scope_user_id"] == 7
        assert lesson["status"] == "active"
        # чужой участник/другой чат не видит (scope-изоляция)
        other = await svc.lesson.select_for_context(
            chat_id=-100, user_id=8,
            query="явное предпочтение формы ответа участника")
        assert other.lessons == ()
        foreign = await svc.lesson.select_for_context(
            chat_id=-200, user_id=7,
            query="явное предпочтение формы ответа участника")
        assert foreign.lessons == ()
        own = await svc.lesson.select_for_context(
            chat_id=-100, user_id=7,
            query="явное предпочтение формы ответа участника")
        assert len(own.lessons) == 1
    finally:
        await db.close()


# ═══ R6a/R6b/R6d: без LLM-рефлексии, сон, случайность ═══════════════════════

def test_no_per_message_llm_reflection_module_is_llm_free():
    src = _jobs_src()
    for forbidden in ("llm_client", "generate(", "chat_with_tools",
                      "llm.generate", "LLMError", "openai", "requests."):
        assert forbidden not in src, forbidden
    import inspect
    params = inspect.signature(mj.ExperienceReviewRunner.__init__).parameters
    assert "llm" not in params
    # предложения — только канонический каталог (не копии реплик)
    assert mj.PROPOSAL_RULE_TOOL_FAILURES in (
        ("tool_usage", "retry_after_typed_failure"),)
    for key in (mj.PROPOSAL_RULE_TOOL_FAILURES, mj.PROPOSAL_RULE_CORRECTIONS,
                mj.PROPOSAL_RULE_PREFERENCE):
        assert key in me.CANONICAL_RECOMMENDATIONS


@pytest.mark.asyncio
async def test_deep_sleep_not_mixed_with_lessons(tmp_path):
    db = await _db(tmp_path)
    try:
        for i in range(3):
            await _insert_tool_failure(db, trace_id=f"sl-{i}", ts=1000 + i)
        assert await mj.tick_experience_review(db) == "completed"
        assert await me.get_service(db).store.count("mca_lessons") == 1
        # пайплайн mca-06 не затронут: ни парадигм, ни dream-лога
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM memory_dream_log")
        assert (await cursor.fetchone())["c"] == 0
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE kind = 'belief'")
        assert (await cursor.fetchone())["c"] == 0
        # отдельный kind job (не sleep.*) и отдельные сущности
        assert mj.REVIEW_JOB_KIND == "experience.review"
        assert "dream_worker" not in _jobs_src()
        assert "graph_facts" not in _jobs_src()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_randomness_boundary_existing_journal_observation_only(tmp_path):
    db = await _db(tmp_path)
    try:
        await _insert_draw(db, draw_id="dr-1")
        obs = await mj.recent_draw_observations(db, limit=5)
        assert len(obs) == 1
        assert obs[0]["draw_id"] == "dr-1"
        assert obs[0]["purpose"] == "exploration"
        # наблюдение read-only: ничего не записано/не изменено
        assert await me.get_service(db).store.count(
            "mca_experience_episodes") == 0
        assert await me.get_service(db).store.count("mca_lessons") == 0
        src = _jobs_src()
        # второго RandomSource/процента нет; истинность/успех не рандомизируются
        assert "import random" not in src
        assert "mca_random_source" not in src
        assert "random.choice" not in src
        assert "randint" not in src
        assert "PROBABILITY" not in src
    finally:
        await db.close()


# ═══ outcome-link / utility (без ложной награды, агрегировано) ══════════════

async def _active_lesson(svc, chat_id=-100):
    lid, ver = await svc.lesson.propose(
        type="tool_usage", scope="chat",
        rule_key="retry_after_typed_failure", scope_chat_id=chat_id)
    assert lid
    assert await svc.lesson.validate(
        lid, evidence=me.ValidationEvidence(
            kind="technical_fix", error_reproduced=True,
            control_example_succeeded=True))
    assert await svc.lesson.activate(lid)
    return lid, ver


@pytest.mark.asyncio
async def test_outcome_link_later_verified_and_utility_updated_once(
        tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(mca_events, "emit_mca_event",
                        lambda name, *, outcome, **fields: captured.append(
                            {"event_name": name, "outcome": outcome,
                             **fields}) or {})
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver = await _active_lesson(svc)
        refs = (LessonRef(lesson_id=lid, version=ver, type="tool_usage",
                          scope="chat", recommendation="x"),)
        assert await svc.record_applications(
            refs, application_ref="tr-ok", trace_id="tr-ok",
            chat_id=-100) == 1
        # независимый проверенный исход ПОЗЖЕ применения (technical failure):
        # эпизод получает created_at времени события (ts события).
        import time
        await _insert_tool_failure(db, trace_id="tr-ok",
                                   ts=int(time.time()) + 5)
        assert await mj.tick_experience_review(db) == "completed"
        lesson = await svc.get_lesson(lid, ver)
        assert lesson["counters_failure"] == 1
        assert lesson["counters_success"] == 0
        util = [c for c in captured if c["event_name"] == "utility_updated"]
        assert len(util) == 1                    # агрегировано на запуск
        assert util[0]["reason_code"] == "utility_updated"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_outcome_link_requires_later_and_verified(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver = await _active_lesson(svc)
        refs = (LessonRef(lesson_id=lid, version=ver, type="tool_usage",
                          scope="chat", recommendation="x"),)
        # исход ДО применения — не подтверждение
        await svc.capture_episode(chat_id=-100, trace_id="early",
                                  outcome_kind="success",
                                  outcome_source="technical", ts=100)
        assert await svc.record_applications(
            refs, application_ref="early", trace_id="early",
            chat_id=-100) == 1
        # unknown-исход (молчание) — не награда
        await svc.capture_episode(chat_id=-100, trace_id="silent",
                                  outcome_kind="unknown",
                                  outcome_source="technical", ts=20_000)
        assert await svc.record_applications(
            refs, application_ref="silent", trace_id="silent",
            chat_id=-100) == 1
        assert await mj.tick_experience_review(db) == "completed"
        lesson = await svc.get_lesson(lid, ver)
        assert lesson["counters_success"] == 0
        assert lesson["counters_failure"] == 0
        assert lesson["counters_unknown"] == 0
    finally:
        await db.close()


# ═══ prune retention (защита связанного) ════════════════════════════════════

@pytest.mark.asyncio
async def test_prune_retention_protects_linked_rows(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        # урок с основаниями-эпизодами (связь сохраняет эпизоды навсегда)
        linked_ids = []
        for i in range(3):
            linked_ids.append(await svc.capture_episode(
                chat_id=-100, trace_id=f"keep-{i}", outcome_kind="failure",
                outcome_source="technical", ts=1000))
        lid, ver = await svc.lesson.propose(
            type="tool_usage", scope="chat",
            rule_key="retry_after_typed_failure", scope_chat_id=-100,
            episode_ids=tuple(linked_ids))
        assert await svc.lesson.validate(
            lid, evidence=me.ValidationEvidence(
                kind="generalization",
                independent_episode_ids=tuple(linked_ids)))
        assert await svc.lesson.activate(lid)
        # старые несвязанные строки
        orphan = await svc.capture_episode(
            chat_id=-100, trace_id="old-orphan", outcome_kind="unknown",
            outcome_source="technical", ts=1000)
        old_ts = 1000
        refs = (LessonRef(lesson_id=lid, version=ver, type="tool_usage",
                          scope="chat", recommendation="x"),)
        assert await svc.record_applications(
            refs, application_ref="app-old", trace_id="app-old",
            chat_id=-100) == 1
        await db.db.execute(
            "UPDATE mca_lesson_applications SET applied_at = ?",
            (old_ts,))
        await db.db.execute(
            "UPDATE mca_experience_episodes SET created_at = ?, updated_at = ?",
            (old_ts, old_ts))
        await db.db.commit()
        assert await mj.tick_experience_review(db) == "completed"
        assert await svc.store.get_episode(linked_ids[0]) is not None
        assert await svc.store.get_episode(orphan) is None
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_lesson_applications")
        assert (await cursor.fetchone())["c"] == 1   # active-урок защищён
    finally:
        await db.close()


# ═══ дедуп/рестарт: повторный прогон не плодит уроки ════════════════════════

@pytest.mark.asyncio
async def test_dedup_restart_no_duplicate_lessons(tmp_path):
    db = await _db(tmp_path)
    try:
        for i in range(3):
            await _insert_tool_failure(db, trace_id=f"dd-{i}", ts=1000 + i)
        assert await mj.tick_experience_review(db) == "completed"
        svc = me.get_service(db)
        assert await svc.store.count("mca_lessons") == 1
        # повторный прогон (в т.ч. после «рестарта» — новый раннер)
        await db.db.execute(
            "UPDATE task_jobs SET status = 'completed', finished_at = 0 "
            "WHERE kind = ?",
            ("experience.review",))
        await db.db.commit()
        assert await mj.tick_experience_review(db) == "completed"
        assert await svc.store.count("mca_lessons") == 1
        db2 = DatabaseService(str(tmp_path / "mca16_d.db"))
        await db2.initialize()
        try:
            # «рестарт»: новый процесс — прямой enqueue+run (курсор наследуется
            # из терминального прогона; урок не дублируется)
            job_id = await mj.enqueue_experience_review(db2)
            assert await mj.ExperienceReviewRunner(db2).run(job_id) == \
                "completed"
            assert await me.get_service(db2).store.count(
                "mca_lessons") == 1
        finally:
            await db2.close()
    finally:
        await db.close()


# ═══ состояние противоречия: suspend, а не спор ════════════════════════════

@pytest.mark.asyncio
async def test_verified_contradiction_suspends_active_lesson(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver = await _active_lesson(svc)
        lesson = await svc.get_lesson(lid, ver)
        from services.provenance import (EvidenceLink, SourceRef,
                                         add_evidence_link,
                                         resolve_source_ref)
        other = SourceRef(store="sqlite", entity_type="episode",
                          entity_id="foreign", resolution="resolved")
        ref = await resolve_source_ref(db, other)
        await add_evidence_link(db, EvidenceLink(
            subject_ref_id=int(lesson["source_ref_id"]),
            source_ref_id=int(ref), link_type="contradicts",
            method="metadata", verification="verified"))
        assert await mj.tick_experience_review(db) == "completed"
        assert (await svc.get_lesson(lid, ver))["status"] == "suspended"
        # suspended не попадает в отбор (не применяется)
        sel = await svc.lesson.select_for_context(
            chat_id=-100, query="повторный вызов инструмента после ошибки")
        assert sel.lessons == ()
    finally:
        await db.close()


# ═══ recheck: несовместимый урок исключается (без выдуманного успеха) ══════

@pytest.mark.asyncio
async def test_recheck_stale_marks_incompatible_lesson(tmp_path, monkeypatch):
    db = await _db(tmp_path)
    try:
        svc = me.get_service(db)
        lid, ver = await _active_lesson(svc)
        monkeypatch.setattr(me, "current_tool_schema_hash",
                            lambda: "changed-schema")
        assert await mj.tick_experience_review(db) == "completed"
        row = await svc.get_lesson(lid, ver)
        assert row["recheck_required"] == 1
        sel = await svc.lesson.select_for_context(
            chat_id=-100, query="повторный вызов инструмента после ошибки")
        assert sel.lessons == ()
    finally:
        await db.close()
